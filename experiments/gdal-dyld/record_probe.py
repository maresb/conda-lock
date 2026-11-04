#!/usr/bin/env python3
"""What happens to a stale per-thread origin record when it is read, refreshed, or held?

Run: python3 record_probe.py --output /tmp/dyld-record
Requires Xcode Command Line Tools and adjacent record_state.c.
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
    ("control", 0),
    ("baseline", 0),
    ("read", 0),
    ("norestore", 0),
    ("refresh", 0),
    ("read", 200),
    ("read", 1000),
    ("hold", 1000),
    ("hold", 5000),
]


def count(c, values):
    """Add one trial's readings to the cell's counters."""
    c["trials"] += 1
    for field in ["x1", "x2", "y", "h1", "h2"]:
        if field in values:
            c[f"{field}_cache"] += values[field] == "cache"
    if values.get("x1") == "cache":
        c["x2_cache_given_x1_cache"] += values["x2"] == "cache"
        c["x2_env_given_x1_cache"] += values["x2"] == "env"
    if values.get("h1") == "cache":
        c["h2_cache_given_h1_cache"] += values["h2"] == "cache"
        c["h2_env_given_h1_cache"] += values["h2"] == "env"
        c["x1_cache_given_h1_cache"] += values["x1"] == "cache"
    if "x2" in values:
        c[f"y_cache_given_x2_{values['x2']}"] += values["y"] == "cache"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("record_state.c")
    shutil.copy2(source, root / source.name)
    binary = root / "record_state"
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
    cases = [(m, ms, t) for m, ms in CELLS for t in range(args.trials)]
    random.Random(974).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode, sleep_ms, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            cached.write_text("data, not an executable\n")
            os.link(cached, installed)
            result = subprocess.run(
                [str(binary), str(cached), str(installed), mode, str(sleep_ms)],
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
            key = mode if not sleep_ms else f"{mode}/sleep{sleep_ms}ms"
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
