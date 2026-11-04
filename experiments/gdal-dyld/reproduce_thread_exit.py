#!/usr/bin/env python3
"""macOS dyld hardlink reproducer without Conda, tracing, or deliberate crashes.

Run: python3 reproduce_thread_exit.py --output /tmp/dyld-thread-exit
Requires Xcode Command Line Tools and adjacent prime_exec.c.
"""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess
import sys

from pathlib import Path


APP = r"""
#include <mach-o/dyld.h>
#include <stdio.h>
int main(void) {
    char path[4096]; uint32_t size = sizeof(path);
    if (_NSGetExecutablePath(path, &size)) return 2;
    printf("launch_path=%s\nmain_image=%s\n", path, _dyld_get_image_name(0));
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    if args.trials < 1:
        parser.error("Use positive trials")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("prime_exec.c")
    shutil.copy2(source, root / source.name)
    launcher, template = root / "launcher", root / "template"
    subprocess.run(
        [
            "xcrun",
            "clang",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(launcher),
        ],
        check=True,
    )
    (root / "identity_app.c").write_text(APP)
    subprocess.run(
        ["xcrun", "clang", "-x", "c", "-", "-o", str(template)],
        input=APP,
        text=True,
        check=True,
    )
    (root / "cache").mkdir()
    (root / "env").mkdir()
    cached, installed = root / "cache/app", root / "env/app"
    cases = [
        (mode, state, method, trial)
        for mode in ["hardlink", "copy"]
        for state in ["cache-dead", "cache-alive", "env-dead", "env-alive"]
        for method in ["exec", "spawn"]
        for trial in range(args.trials)
    ]
    random.Random(969).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode, state, method, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            shutil.copy2(template, cached)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            result = subprocess.run(
                [str(launcher), state, str(cached), str(installed), method, "1"],
                capture_output=True,
                text=True,
                env=env,
                check=True,
                timeout=10,
            )
            values = dict(
                s.split("=", 1) for s in result.stdout.splitlines() if "=" in s
            )
            assert values["launch_path"] == str(installed), values
            assert values["main_image"] in {str(cached), str(installed)}, values
            key = f"{mode}/{state}/{method}"
            counts[key]["launches"] += 1
            counts[key]["cache_path"] += values["main_image"] == str(cached)
            counts[key]["env_path"] += values["main_image"] == str(installed)
            events.write(
                json.dumps(
                    {
                        "event": "launch",
                        "case": key,
                        "trial": trial,
                        "returncode": result.returncode,
                        "values": values,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
