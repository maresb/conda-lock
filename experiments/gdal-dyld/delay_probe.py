#!/usr/bin/env python3
"""Does a delay between the installer's exit and the launch reduce wrong-path launches?

A finished process looks up the cache alias from its main thread, then after a
delay a launcher process looks up the environment alias and spawns it, like
`micromamba run` after `micromamba create`.

Run: python3 delay_probe.py --output /tmp/dyld-delay
Requires Xcode Command Line Tools and adjacent touch_exit.c, prime_exec.c, and
reproduce_thread_exit.py.
"""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess
import sys
import time

from pathlib import Path

from reproduce_thread_exit import APP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--delays", default="0,0.2,0.5,1,5,20")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    binaries = {}
    for name in ["touch_exit", "prime_exec"]:
        source = Path(__file__).with_name(name + ".c")
        shutil.copy2(source, root / source.name)
        binaries[name] = root / name
        subprocess.run(
            [
                "xcrun",
                "clang",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binaries[name]),
            ],
            check=True,
        )
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
    delays = [float(d) for d in args.delays.split(",")]
    cases = [("hardlink", d, t) for d in delays for t in range(args.trials)]
    cases += [("copy", 0.0, t) for t in range(args.trials)]
    random.Random(975).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode, delay, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            shutil.copy2(template, cached)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            subprocess.run(
                [str(binaries["touch_exit"]), str(cached), "0"],
                env=env,
                check=True,
                timeout=10,
            )
            if delay:
                time.sleep(delay)
            result = subprocess.run(
                [
                    str(binaries["prime_exec"]),
                    "env-dead",
                    str(cached),
                    str(installed),
                    "spawn",
                    "0",
                ],
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
            key = f"{mode}/delay{delay:g}s"
            counts[key]["launches"] += 1
            counts[key]["cache_path"] += values["main_image"] == str(cached)
            counts[key]["env_path"] += values["main_image"] == str(installed)
            events.write(
                json.dumps(
                    {"event": "launch", "case": key, "trial": trial, "values": values}
                )
                + "\n"
            )
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
