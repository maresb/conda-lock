#!/usr/bin/env python3
"""Third design of the record probe: the main thread resets the fallback before every read.

Run: python3 record_probe3.py --output /tmp/dyld-record3
Requires Xcode Command Line Tools and adjacent record_state3.c and record_probe.py.
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

from record_probe import count


CELLS = [
    ("control", 0),
    ("baseline", 0),
    ("read", 0),
    ("refresh", 0),
    ("read", 200),
    ("read", 1000),
    ("hold", 1000),
    ("hold", 5000),
    ("oppose", 0),
    ("oppose-control", 0),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("record_state3.c")
    shutil.copy2(source, root / source.name)
    binary = root / "record_state3"
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
            pairs = [s.split("=", 1) for s in result.stdout.splitlines() if "=" in s]
            resets = [v for k, v in pairs if k == "reset"]
            values = dict(pair for pair in pairs if pair[0] != "reset")
            values["resets"] = len(resets)
            assert resets and all(r == "env" for r in resets), (resets, values)
            assert values["main"] == "env", values
            assert all(
                v in {"cache", "env"} for k, v in values.items() if k != "resets"
            ), values
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
