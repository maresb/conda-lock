#!/usr/bin/env python3
"""macOS hardlink/dyld reproducer. Run with Python 3 and Xcode Command Line Tools."""

import os
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path


if sys.platform != "darwin":
    sys.exit("This reproducer requires macOS.")

READER = r"""
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(int argc, char **argv) {
    (void)argc;
    puts("ready"); fflush(stdout);
    for (;;) {
        int fd = open(argv[1], O_RDONLY);
        if (fd < 0) return 1;
        close(fd);
        usleep(50);
    }
}
"""

with tempfile.TemporaryDirectory(prefix="dyld-hardlink-") as temporary:
    root = Path(temporary).resolve()

    def build(name, source, *flags):
        subprocess.run(
            ["xcrun", "clang", "-x", "c", "-", *flags, "-o", str(root / name)],
            input=source,
            text=True,
            check=True,
        )

    build(
        "libanswer.dylib",
        "int answer(void) { return 42; }",
        "-dynamiclib",
        "-Wl,-install_name,@rpath/libanswer.dylib",
    )
    build(
        "app",
        "extern int answer(void); int main(void) { return answer() != 42; }",
        "-L" + str(root),
        "-lanswer",
        "-Wl,-rpath,@loader_path/../lib",
    )
    build("reader", READER)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    first_error = ""
    for mode, concurrent_reader in [
        ("hardlink", False),
        ("hardlink", True),
        ("copy", True),
    ]:
        failures = 0
        for trial in range(30):
            # Fresh files for each launch, so previous trials cannot affect them.
            with tempfile.TemporaryDirectory(dir=root) as directory:
                case = Path(directory)
                (case / "env/bin").mkdir(parents=True)
                (case / "env/lib").mkdir()
                cached, installed = case / "cached-app", case / "env/bin/app"
                shutil.copy2(root / "app", cached)
                shutil.copy2(root / "libanswer.dylib", case / "env/lib/libanswer.dylib")
                (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
                reader = None
                try:
                    if concurrent_reader:
                        reader = subprocess.Popen(
                            [str(root / "reader"), str(cached)],
                            stdout=subprocess.PIPE,
                            text=True,
                        )
                        assert reader.stdout is not None
                        assert reader.stdout.readline().strip() == "ready"
                    result = subprocess.run(
                        [str(installed)],
                        env=environment,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    if reader is not None:
                        reader.terminate()
                        reader.wait()
                        assert reader.stdout is not None
                        reader.stdout.close()
                failures += result.returncode != 0
                if result.returncode and not first_error:
                    first_error = result.stderr
        print(
            f"{mode}, cache reader={concurrent_reader}: {failures}/30 failures",
            flush=True,
        )
    if first_error:
        print("\nFirst loader error:\n" + first_error)
