#!/usr/bin/env python3
"""Test sequential cache/link operations without a concurrent reader."""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess
import time

from pathlib import Path

from trigger_probe import ORIGINAL_UUID, fingerprint


def change_fixture(operation, cached, installed):
    if operation == "intact":
        return
    if operation == "hash-then-relink":
        cached.read_bytes()
    installed.unlink()
    (shutil.copy2 if operation == "copy-then-hash" else os.link)(cached, installed)
    if operation in {
        "relink-then-hash",
        "relink-hash-stat-env",
        "relink-hash-open-env",
        "copy-then-hash",
    }:
        cached.read_bytes()
    if operation == "relink-then-open":
        with cached.open("rb"):
            pass
    if operation == "relink-hash-stat-env":
        installed.stat()
    if operation == "relink-hash-open-env":
        with installed.open("rb"):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micromamba", type=Path, required=True)
    parser.add_argument("--root-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Requires this experiment's authorized GitHub runner")
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.root_prefix
    name = "gdal-sequential-links"
    command = [str(args.micromamba), "-r", str(root)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    lock = Path(__file__).with_name("fixtures") / "conda-osx-arm64.lock"
    with (args.output / "create.log").open("w") as log:
        subprocess.run(
            [*command, "create", "-y", "-n", name, "-f", str(lock)],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=240,
        )
    installed = root / "envs" / name / "bin/gdalinfo"
    # Construct the known original path without looking up or reading the binary.
    cached = (
        root
        / "pkgs/https/repo.anaconda.com/pkgs/main/osx-arm64/libgdal-3.6.2-h51eea9d_5/bin/gdalinfo"
    )
    operations = [
        "intact",
        "relink",
        "hash-then-relink",
        "relink-then-hash",
        "relink-hash-stat-env",
        "relink-hash-open-env",
        "copy-then-hash",
        "relink-then-open",
    ]
    groups = [(op, block, 20) for op in operations for block in range(3)]
    random.Random(964).shuffle(groups)
    groups.insert(0, ("pristine", 0, 40))
    counts = collections.defaultdict(
        lambda: {"launches": 0, "failures": 0, "original_signature": 0}
    )
    with (args.output / "events.jsonl").open("w", buffering=1) as events:
        for operation, block, trials in groups:
            if operation != "pristine":
                installed.unlink()
                os.link(cached, installed)
            for trial in range(trials):
                if operation != "pristine":
                    change_fixture(operation, cached, installed)
                started = time.time_ns()
                proc = subprocess.Popen(
                    [*command, "run", "-n", name, "gdalinfo", "--version"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = proc.communicate(timeout=30)
                signature = (
                    "Library not loaded: @rpath/libcrypto.3.dylib" in stderr
                    and ORIGINAL_UUID in stderr
                    and "/pkgs/" in stderr
                )
                event = {
                    "event": "launch",
                    "case": operation,
                    "block": block,
                    "trial": trial,
                    "pid": proc.pid,
                    "started_ns": started,
                    "ended_ns": time.time_ns(),
                    "returncode": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "original_signature": signature,
                    "retry": False,
                }
                events.write(json.dumps(event) + "\n")
                counts[operation]["launches"] += 1
                counts[operation]["failures"] += proc.returncode != 0
                counts[operation]["original_signature"] += signature
                if proc.returncode:
                    print("FAIL", operation, block, trial, stderr.strip(), flush=True)
            snapshots = {
                "cache_app": fingerprint(cached),
                "env_app": fingerprint(installed),
                "cache_lib": fingerprint(
                    cached.parent.parent / "lib/libgdal.32.3.6.2.dylib"
                ),
                "env_lib": fingerprint(
                    installed.parent.parent / "lib/libgdal.32.3.6.2.dylib"
                ),
            }
            assert snapshots["cache_app"]["sha256"] == snapshots["env_app"]["sha256"]
            events.write(
                json.dumps(
                    {
                        "event": "files",
                        "case": operation,
                        "block": block,
                        "files": snapshots,
                    }
                )
                + "\n"
            )
            (args.output / "summary.json").write_text(
                json.dumps(counts, indent=2) + "\n"
            )
            print("DONE", operation, block, json.dumps(counts[operation]), flush=True)


if __name__ == "__main__":
    main()
