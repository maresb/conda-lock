#!/usr/bin/env python3
"""Exited-thread reproducer with the cache lookup in a separate, finished process.

Models `micromamba create` (a process looks up the cache alias and exits) followed
by `micromamba run` (another process launches the environment alias).

Run: python3 reproduce_cross_process.py --output /tmp/dyld-cross-process
Requires Xcode Command Line Tools and adjacent touch_exit.c, prime_exec.c,
and reproduce_thread_exit.py.
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

from reproduce_thread_exit import APP


def compile_c(source, binary):
    subprocess.run(
        [
            "xcrun",
            "clang",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    if args.trials < 1:
        parser.error("Use positive trials")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    binaries = {}
    for name in ["touch_exit", "prime_exec"]:
        source = Path(__file__).with_name(name + ".c")
        shutil.copy2(source, root / source.name)
        binaries[name] = root / name
        compile_c(source, binaries[name])
    template = root / "template"
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
    # toucher: which exiting thread of a separate process looks up the cache alias.
    # launch: python spawns the app directly, or a launcher process (main thread
    # looks up the environment alias first, like a PATH search) spawns or execs it.
    cases = [
        (mode, toucher, launch, trial)
        for mode in ["hardlink", "copy"]
        for toucher in ["none", "main", "worker1", "worker4"]
        for launch in ["python", "launcher-spawn", "launcher-exec"]
        for trial in range(args.trials)
    ]
    random.Random(970).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode, toucher, launch, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            shutil.copy2(template, cached)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            if toucher != "none":
                workers = "0" if toucher == "main" else toucher.removeprefix("worker")
                subprocess.run(
                    [str(binaries["touch_exit"]), str(cached), workers],
                    env=env,
                    check=True,
                    timeout=10,
                )
            if launch == "python":
                command = [str(installed)]
            else:
                method = launch.removeprefix("launcher-")
                command = [
                    str(binaries["prime_exec"]),
                    "env-dead",
                    str(cached),
                    str(installed),
                    method,
                    "0",
                ]
            result = subprocess.run(
                command, capture_output=True, text=True, env=env, check=True, timeout=10
            )
            values = dict(
                s.split("=", 1) for s in result.stdout.splitlines() if "=" in s
            )
            assert values["launch_path"] == str(installed), values
            assert values["main_image"] in {str(cached), str(installed)}, values
            key = f"{mode}/{toucher}/{launch}"
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
