#!/usr/bin/env python3
"""After a wrong-path launch on a retained inode, what makes a retry pass?

Each trial: fresh inode, a launcher whose cache worker exits before it spawns
the identity app (the reliable stale-record launch), then one retry of the
same inode under one condition. Only trials whose first launch chose the cache
path are informative; both outcomes are recorded.

Run: python3 retry_probe.py --output /tmp/dyld-retry
Requires Xcode Command Line Tools and adjacent prime_exec.c, spawn_only.c,
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
import time

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


def chose_cache(result, cached, installed):
    values = dict(s.split("=", 1) for s in result.stdout.splitlines() if "=" in s)
    assert values["launch_path"] == str(installed), values
    assert values["main_image"] in {str(cached), str(installed)}, values
    return values["main_image"] == str(cached)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    binaries = {}
    for name in ["prime_exec", "spawn_only"]:
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
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    first = [
        str(binaries["prime_exec"]),
        "cache-dead",
        str(cached),
        str(installed),
        "spawn",
        "1",
    ]
    # (condition, delay seconds, command)
    conditions = {
        "spawn-no-lookup": (0, [str(binaries["spawn_only"]), str(installed)]),
        "spawn-no-lookup-2s": (2, [str(binaries["spawn_only"]), str(installed)]),
        "launcher-lookup-then-spawn": (
            0,
            [
                str(binaries["prime_exec"]),
                "env-dead",
                str(cached),
                str(installed),
                "spawn",
                "0",
            ],
        ),
        "launcher-lookup-then-exec": (
            0,
            [
                str(binaries["prime_exec"]),
                "env-dead",
                str(cached),
                str(installed),
                "exec",
                "0",
            ],
        ),
        "python-direct": (0, [str(installed)]),
    }
    cases = [(c, t) for c in conditions for t in range(args.trials)]
    random.Random(973).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for condition, trial in cases:
            installed.unlink(missing_ok=True)
            cached.unlink(missing_ok=True)
            shutil.copy2(template, cached)
            os.link(cached, installed)
            result = subprocess.run(
                first, capture_output=True, text=True, env=env, check=True, timeout=10
            )
            first_cache = chose_cache(result, cached, installed)
            delay, command = conditions[condition]
            if delay:
                time.sleep(delay)
            retry = subprocess.run(
                command, capture_output=True, text=True, env=env, check=True, timeout=10
            )
            retry_cache = chose_cache(retry, cached, installed)
            # A second retry with no lookup, to see whether the first retry changed anything.
            again = subprocess.run(
                [str(binaries["spawn_only"]), str(installed)],
                capture_output=True,
                text=True,
                env=env,
                check=True,
                timeout=10,
            )
            again_cache = chose_cache(again, cached, installed)
            c = counts[condition]
            c["trials"] += 1
            c["first_cache"] += first_cache
            if first_cache:
                c["retry_cache_after_failed_first"] += retry_cache
                c["second_retry_cache_after_failed_first"] += again_cache
            events.write(
                json.dumps(
                    {
                        "event": "trial",
                        "case": condition,
                        "trial": trial,
                        "first_cache": first_cache,
                        "retry_cache": retry_cache,
                        "second_retry_cache": again_cache,
                    }
                )
                + "\n"
            )
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
