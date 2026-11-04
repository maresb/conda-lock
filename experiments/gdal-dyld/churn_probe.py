#!/usr/bin/env python3
"""Does background thread turnover, rather than time alone, remove a freed identity's stale answer?

Runs record_state in its read mode with a pause before X, with and without a
separate process that creates and joins threads continuously.

Run: python3 churn_probe.py --output /tmp/dyld-churn
Requires Xcode Command Line Tools and adjacent record_state.c, churn.c, record_probe.py.
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

from record_probe import count


SLEEPS_MS = [0, 200, 1000]


def compile_c(root, name):
    source = Path(__file__).with_name(f"{name}.c")
    shutil.copy2(source, root / source.name)
    binary = root / name
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
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--blocks", type=int, default=4)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    state, churn = compile_c(root, "record_state"), compile_c(root, "churn")
    (root / "cache").mkdir()
    (root / "env").mkdir()
    cached, installed = root / "cache/file", root / "env/file"
    per_block = args.trials // args.blocks
    rng = random.Random(976)
    counts = collections.defaultdict(collections.Counter)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for block in range(args.blocks):
            for churning in [False, True]:
                process = None
                if churning:
                    process = subprocess.Popen([str(churn), "4"])
                    time.sleep(0.5)
                try:
                    cases = [(ms, t) for ms in SLEEPS_MS for t in range(per_block)]
                    rng.shuffle(cases)
                    for sleep_ms, t in cases:
                        installed.unlink(missing_ok=True)
                        cached.unlink(missing_ok=True)
                        cached.write_text("data, not an executable\n")
                        os.link(cached, installed)
                        result = subprocess.run(
                            [
                                str(state),
                                str(cached),
                                str(installed),
                                "read",
                                str(sleep_ms),
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=30,
                        )
                        values = dict(
                            s.split("=", 1)
                            for s in result.stdout.splitlines()
                            if "=" in s
                        )
                        assert values["main"] == "env", values
                        key = f"read/sleep{sleep_ms}ms/churn-{'on' if churning else 'off'}"
                        count(counts[key], values)
                        events.write(
                            json.dumps(
                                {
                                    "event": "trial",
                                    "case": key,
                                    "block": block,
                                    "trial": t,
                                    "values": values,
                                }
                            )
                            + "\n"
                        )
                finally:
                    if process:
                        process.terminate()
                        process.wait(timeout=10)
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
