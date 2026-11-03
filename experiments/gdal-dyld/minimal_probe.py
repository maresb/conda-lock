#!/usr/bin/env python3
"""Exercise Mach-O executable and dylib hardlinks without a package manager."""

import argparse
import collections
import json
import os
import platform
import random
import shutil
import subprocess

from pathlib import Path


SOURCES = {
    "inner.c": "int inner(void) { return 42; }\n",
    "outer.c": "extern int inner(void); int outer(void) { return inner(); }\n",
    "app.c": '#include <stdio.h>\nextern int outer(void); int main(void) { printf("%d\\n", outer()); return 0; }\n',
    "dlopen.c": r"""#include <dlfcn.h>
#include <stdio.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    void *handle = dlopen(argv[1], RTLD_NOW);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    int (*outer)(void) = (int (*)(void))dlsym(handle, "outer");
    if (!outer) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    printf("%d\n", outer());
    return 0;
}
""",
    "getpath.c": r"""#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/param.h>
int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        char path[MAXPATHLEN];
        int fd = open(argv[i], O_RDONLY);
        if (fd < 0 || fcntl(fd, F_GETPATH, path) != 0) { perror(argv[i]); return 1; }
        printf("%s => %s\n", argv[i], path);
        close(fd);
    }
    return 0;
}
""",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--macos-version", help="Set both Mach-O minimum OS and SDK version"
    )
    parser.add_argument(
        "--posix-spawn", action="store_true", help="Launch directly with posix_spawn"
    )
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("This experiment requires macOS")
    if args.iterations < 1:
        parser.error("iterations must be positive")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name, source in SOURCES.items():
        (root / name).write_text(source)
    cache = root / "cache"
    for name in ["app/bin", "outer/lib", "inner/lib"]:
        (cache / name).mkdir(parents=True)
    app = cache / "app/bin/app"
    outer = cache / "outer/lib/libouter.dylib"
    inner = cache / "inner/lib/libinner.dylib"

    def compile_c(arguments):
        flags = []
        if args.macos_version:
            flags = [
                "-mmacosx-version-min=" + args.macos_version,
                "-Wl,-platform_version,macos,"
                + args.macos_version
                + ","
                + args.macos_version,
            ]
        subprocess.run(["xcrun", "clang", *arguments, *flags], cwd=root, check=True)

    compile_c(
        [
            "-dynamiclib",
            "inner.c",
            "-Wl,-install_name,@rpath/libinner.dylib",
            "-o",
            str(inner),
        ]
    )
    compile_c(
        [
            "-dynamiclib",
            "outer.c",
            str(inner),
            "-Wl,-install_name,@rpath/libouter.dylib",
            "-Wl,-rpath,@loader_path",
            "-o",
            str(outer),
        ]
    )
    compile_c(["app.c", str(outer), "-Wl,-rpath,@loader_path/../lib", "-o", str(app)])
    compile_c(["dlopen.c", "-o", "dlopen"])
    compile_c(["getpath.c", "-o", "getpath"])
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sw_vers": subprocess.check_output(["sw_vers"], text=True),
        "clang": subprocess.check_output(["xcrun", "clang", "--version"], text=True),
        "iterations": args.iterations,
        "macos_version": args.macos_version,
        "posix_spawn": args.posix_spawn,
        "seed": 964,
        "load_commands": {
            str(p): subprocess.check_output(["otool", "-l", str(p)], text=True)
            for p in [app, outer, inner]
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    rng = random.Random(964)
    counts = collections.defaultdict(lambda: {"launches": 0, "failures": 0})
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for iteration in range(args.iterations):
            cases = [
                (mode, touch, loader)
                for mode in ["hardlink", "executable", "library", "copy"]
                for touch in ["none", "cache", "environment"]
                for loader in ["linked", "dlopen"]
            ]
            rng.shuffle(cases)
            for case_no, (mode, touch, loader) in enumerate(cases):
                prefix = root / "envs" / (f"{iteration:04d}-{case_no:02d}")
                (prefix / "bin").mkdir(parents=True)
                (prefix / "lib").mkdir()
                targets = [
                    (app, prefix / "bin/app", mode in ["executable", "copy"]),
                    (outer, prefix / "lib/libouter.dylib", mode in ["library", "copy"]),
                    (inner, prefix / "lib/libinner.dylib", True),
                ]
                for source, target, copy in targets:
                    if copy:
                        shutil.copy2(source, target)
                    else:
                        os.link(source, target)
                # Exercise path access order independently of elapsed time.
                if touch != "none":
                    for source, target, _ in targets:
                        with (source if touch == "cache" else target).open(
                            "rb"
                        ) as stream:
                            stream.read(1)
                command = (
                    [str(prefix / "bin/app")]
                    if loader == "linked"
                    else [str(root / "dlopen"), str(prefix / "lib/libouter.dylib")]
                )
                if args.posix_spawn:
                    stdout_path, stderr_path = prefix / "stdout", prefix / "stderr"
                    with stdout_path.open("w") as out, stderr_path.open("w") as err:
                        pid = os.posix_spawn(
                            command[0],
                            command,
                            env,
                            file_actions=[
                                (os.POSIX_SPAWN_DUP2, out.fileno(), 1),
                                (os.POSIX_SPAWN_DUP2, err.fileno(), 2),
                            ],
                        )
                        _, status = os.waitpid(pid, 0)
                    result = subprocess.CompletedProcess(
                        command,
                        os.waitstatus_to_exitcode(status),
                        stdout_path.read_text(),
                        stderr_path.read_text(),
                    )
                else:
                    result = subprocess.run(
                        command, env=env, capture_output=True, text=True
                    )
                key = "/".join([mode, touch, loader])
                counts[key]["launches"] += 1
                counts[key]["failures"] += result.returncode != 0
                events.write(
                    json.dumps(
                        {
                            "iteration": iteration,
                            "case": key,
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                    )
                    + "\n"
                )
                # Keep path-probe diagnostics separate and after the primary observation.
                if result.returncode != 0 and counts[key]["failures"] <= 3:
                    probe = subprocess.run(
                        [
                            str(root / "getpath"),
                            str(prefix / "bin/app"),
                            str(prefix / "lib/libouter.dylib"),
                        ],
                        text=True,
                        capture_output=True,
                    )
                    events.write(
                        json.dumps(
                            {
                                "iteration": iteration,
                                "case": key,
                                "diagnostic": "F_GETPATH",
                                "stdout": probe.stdout,
                                "stderr": probe.stderr,
                            }
                        )
                        + "\n"
                    )
                shutil.rmtree(prefix)
            (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
            if iteration % 10 == 0 or iteration == args.iterations - 1:
                print(f"ITERATION {iteration} {json.dumps(counts)}", flush=True)


if __name__ == "__main__":
    main()
