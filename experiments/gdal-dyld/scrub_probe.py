#!/usr/bin/env python3
"""Test whether idle threads or later environment lookups change the stale result.

Cells vary what happens between the cache worker's exit and the launch:
dead dummy threads, live holder threads, or live threads that looked up the
environment alias before the stale worker exited (candidate evictors).

Run: python3 scrub_probe.py --output /tmp/dyld-scrub
Requires Xcode Command Line Tools and adjacent scrub_exec.c and
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

from pathlib import Path

from reproduce_thread_exit import APP


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
    source = Path(__file__).with_name("scrub_exec.c")
    shutil.copy2(source, root / source.name)
    launcher, template = root / "scrub_exec", root / "template"
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
    other = root / "other-file"
    other.write_text("unrelated\n")
    # (mode, stale, dummies, holders, evictors, evictor target, method)
    cells = [
        ("hardlink", 1, 0, 0, 0, "installed", "spawn"),
        ("hardlink", 1, 0, 0, 0, "installed", "exec"),
        ("hardlink", 0, 0, 0, 0, "installed", "spawn"),
        ("copy", 1, 0, 0, 0, "installed", "spawn"),
    ]
    cells += [("hardlink", 1, d, 0, 0, "installed", "spawn") for d in [1, 2, 4, 8]]
    cells += [("hardlink", 1, 0, h, 0, "installed", "spawn") for h in [1, 2, 4]]
    cells += [
        ("hardlink", 1, 0, 0, e, "installed", "spawn") for e in [1, 3, 5, 6, 7, 8, 10]
    ]
    # Matched controls: the same live threads, created before the worker exits,
    # that look up nothing or an unrelated file instead of the environment alias.
    cells += [
        ("hardlink", 1, 0, 0, e, t, "spawn") for e in [7, 10] for t in ["none", "other"]
    ]
    cases = [(*cell, trial) for cell in cells for trial in range(args.trials)]
    random.Random(971).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode, stale, dummies, holders, evictors, target, method, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            shutil.copy2(template, cached)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            result = subprocess.run(
                [
                    str(launcher),
                    str(cached),
                    str(installed),
                    method,
                    str(stale),
                    str(dummies),
                    str(holders),
                    str(evictors),
                    {"installed": str(installed), "none": "none", "other": str(other)}[
                        target
                    ],
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
            suffix = "" if target == "installed" else f"-{target}"
            key = f"{mode}/stale{stale}/dummies{dummies}/holders{holders}/evictors{evictors}{suffix}/{method}"
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
