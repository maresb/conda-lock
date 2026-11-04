#!/usr/bin/env python3
"""Does a thread without a record follow an exited thread's lookup, and does the main thread's fsgetpath matter?

Run: python3 fallback_probe.py --output /tmp/dyld-fallback
Requires Xcode Command Line Tools and adjacent fallback_state.c.
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


CELLS = [
    (reader, worker, mainread)
    for reader in ["pre", "none"]
    for worker in ["exited", "alive", "none"]
    for mainread in [0, 1]
    if reader == "pre" or worker == "exited"
]


def count(c, values):
    c["trials"] += 1
    for field in ["r", "x1", "x2", "y"]:
        if field in values:
            c[f"{field}_cache"] += values[field] == "cache"
    if values.get("x1") == "cache":
        c["x2_cache_given_x1_cache"] += values["x2"] == "cache"
    if values.get("x1") == "env":
        c["y_cache_given_x1_env"] += values["y"] == "cache"
    if "r" in values:
        c[f"x1_cache_given_r_{values['r']}"] += values["x1"] == "cache"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("fallback_state.c")
    shutil.copy2(source, root / source.name)
    binary = root / "fallback_state"
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
    (root / "cache").mkdir()
    (root / "env").mkdir()
    cached, installed = root / "cache/file", root / "env/file"
    cases = [(cell, t) for cell in CELLS for t in range(args.trials)]
    random.Random(975).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for (reader, worker, mainread), trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            cached.write_text("data, not an executable\n")
            os.link(cached, installed)
            result = subprocess.run(
                [
                    str(binary),
                    str(cached),
                    str(installed),
                    reader,
                    worker,
                    str(mainread),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            values = dict(
                s.split("=", 1) for s in result.stdout.splitlines() if "=" in s
            )
            assert values["main"] == "env", values
            assert all(v in {"cache", "env"} for v in values.values()), values
            key = f"reader-{reader}/worker-{worker}/mainread-{mainread}"
            count(counts[key], values)
            events.write(
                json.dumps(
                    {"event": "trial", "case": key, "trial": trial, "values": values}
                )
                + "\n"
            )
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
