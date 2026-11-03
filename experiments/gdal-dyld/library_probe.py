#!/usr/bin/env python3
"""Isolate dylib pathname races from executable paths and inherited RPATHs."""

import argparse
import collections
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import tempfile

from pathlib import Path


SOURCES = {
    "inner.c": "int inner(void) { return 42; }\n",
    "outer.c": r"""#include <dlfcn.h>
extern int inner(void);
int outer(void) { return inner(); }
const char *outer_path(void) {
    Dl_info info;
    return dladdr((void *)&outer_path, &info) ? info.dli_fname : "unknown";
}
""",
    "linked.c": r"""#include <stdio.h>
extern int outer(void);
extern const char *outer_path(void);
int main(void) { puts(outer_path()); return outer() != 42; }
""",
    "dlopen.c": r"""#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    void *handle = dlopen(argv[1], RTLD_NOW);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    int (*outer)(void) = (int (*)(void))dlsym(handle, "outer");
    const char *(*outer_path)(void) =
        (const char *(*)(void))dlsym(handle, "outer_path");
    if (!outer || !outer_path) return 2;
    puts(outer_path());
    return outer() != 42;
}
""",
    "reader.c": r"""#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static volatile sig_atomic_t stopped = 0;
static void stop(int unused) { (void)unused; stopped = 1; }
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    unsigned int pause_us = (unsigned int)strtoul(argv[3], NULL, 10);
    signal(SIGTERM, stop);
    unsigned long count = 0;
    puts("ready"); fflush(stdout);
    while (!stopped) {
        if (!strcmp(argv[1], "stat")) {
            struct stat st;
            if (stat(argv[2], &st)) { perror("stat"); return 1; }
        } else {
            int fd = open(argv[2], O_RDONLY);
            if (fd < 0) { perror("open"); return 1; }
            close(fd);
        }
        ++count;
        if (pause_us) usleep(pause_us);
    }
    printf("%lu\n", count);
    return 0;
}
""",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--reader-pause-us", type=int, default=50)
    parser.add_argument(
        "--modes", nargs="+", choices=["hardlink", "copy"], default=["hardlink", "copy"]
    )
    parser.add_argument(
        "--operations",
        nargs="+",
        choices=["none", "open", "stat"],
        default=["none", "open"],
    )
    parser.add_argument(
        "--loaders",
        nargs="+",
        choices=["linked", "dlopen"],
        default=["linked", "dlopen"],
    )
    parser.add_argument(
        "--layouts",
        nargs="+",
        choices=["rpath", "loader_path"],
        default=["rpath", "loader_path"],
    )
    args = parser.parse_args()
    if platform.system() != "Darwin" or args.trials < 1 or args.reader_pause_us < 0:
        parser.error("Requires macOS and positive trials")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name, source in SOURCES.items():
        (root / name).write_text(source)

    def build(source, target, *flags):
        subprocess.run(
            [
                "xcrun",
                "clang",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(root / source),
                *flags,
                "-o",
                str(target),
            ],
            check=True,
        )

    build("reader.c", root / "reader")
    for layout in args.layouts:
        template = root / "templates" / layout
        template.mkdir(parents=True)
        inner_name = (
            "@rpath/libinner.dylib"
            if layout == "rpath"
            else "@loader_path/private/libinner.dylib"
        )
        build(
            "inner.c",
            template / "libinner.dylib",
            "-dynamiclib",
            "-Wl,-install_name," + inner_name,
        )
        build(
            "outer.c",
            template / "libouter.dylib",
            "-dynamiclib",
            str(template / "libinner.dylib"),
            "-Wl,-install_name,@rpath/libouter.dylib",
            "-Wl,-rpath,@loader_path",
        )
        build(
            "linked.c",
            template / "linked",
            str(template / "libouter.dylib"),
            "-Wl,-rpath,@loader_path/../lib",
        )
        build("dlopen.c", template / "dlopen", "-Wl,-rpath,@loader_path/../lib")
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sw_vers": subprocess.check_output(["sw_vers"], text=True),
        "clang": subprocess.check_output(["xcrun", "clang", "--version"], text=True),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trials": args.trials,
        "seed": 964,
        "reader_pause_us": args.reader_pause_us,
        "load_commands": {
            str(p.relative_to(root)): subprocess.check_output(
                ["otool", "-l", str(p)], text=True
            )
            for p in (root / "templates").glob("*/*")
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    environment = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    counts = collections.defaultdict(
        lambda: {"launches": 0, "failures": 0, "success_cache_path": 0}
    )

    def launch(layout, loader, mode, operation, force_cache=False):
        template = root / "templates" / layout
        with tempfile.TemporaryDirectory(dir=root, prefix="case-") as directory:
            case = Path(directory)
            cache = case / "cache"
            cache.mkdir()
            prefix = case / "env"
            (prefix / "bin").mkdir(parents=True)
            (prefix / "lib/private").mkdir(parents=True)
            cached, installed = cache / "libouter.dylib", prefix / "lib/libouter.dylib"
            shutil.copy2(template / loader, prefix / "bin/app")
            shutil.copy2(template / "libouter.dylib", cached)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            inner_dir = prefix / ("lib" if layout == "rpath" else "lib/private")
            shutil.copy2(template / "libinner.dylib", inner_dir / "libinner.dylib")
            command = [str(prefix / "bin/app")]
            if loader == "dlopen":
                command.append(str(cached if force_cache else installed))
            reader = None
            reader_count = 0
            try:
                if operation != "none":
                    reader = subprocess.Popen(
                        [
                            str(root / "reader"),
                            operation,
                            str(cached),
                            str(args.reader_pause_us),
                        ],
                        stdout=subprocess.PIPE,
                        text=True,
                    )
                    assert reader.stdout is not None
                    assert reader.stdout.readline().strip() == "ready"
                result = subprocess.run(
                    command, env=environment, capture_output=True, text=True, timeout=20
                )
            finally:
                if reader is not None:
                    reader.terminate()
                    tail, _ = reader.communicate(timeout=10)
                    assert reader.returncode == 0, reader.returncode
                    reader_count = int(tail.strip())
                    assert reader_count > 0
            paths = [cached, installed, prefix / "bin/app"]
            return {
                "case": "/".join([layout, loader, mode, operation]),
                "force_cache": force_cache,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success_cache_path": result.returncode == 0
                and "/cache/" in result.stdout,
                "reader_operations": reader_count,
                "files": {
                    str(p.relative_to(case)): {
                        "inode": p.stat().st_ino,
                        "nlink": p.stat().st_nlink,
                    }
                    for p in paths
                },
            }

    with (root / "controls.jsonl").open("w", buffering=1) as controls:
        for layout in args.layouts:
            result = launch(layout, "dlopen", "copy", "none", force_cache=True)
            controls.write(json.dumps(result) + "\n")
            assert (result["returncode"] != 0) == (layout == "loader_path"), result

    cases = [
        (layout, loader, mode, operation, trial)
        for layout in args.layouts
        for loader in args.loaders
        for mode in args.modes
        for operation in args.operations
        for trial in range(args.trials)
    ]
    random.Random(964).shuffle(cases)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for number, (layout, loader, mode, operation, trial) in enumerate(cases):
            result = launch(layout, loader, mode, operation)
            result["trial"] = trial
            events.write(json.dumps(result) + "\n")
            cell = counts[result["case"]]
            cell["launches"] += 1
            cell["failures"] += result["returncode"] != 0
            cell["success_cache_path"] += result["success_cache_path"]
            (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
            if (number + 1) % 40 == 0:
                print(f"Completed {number + 1}/{len(cases)}", flush=True)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
