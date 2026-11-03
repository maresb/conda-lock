#!/usr/bin/env python3
"""Test single cache lookups while actual GDAL is suspended before dyld startup."""

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
    name = "gdal-suspended"
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
    cached = (
        root
        / "pkgs/https/repo.anaconda.com/pkgs/main/osx-arm64/libgdal-3.6.2-h51eea9d_5/bin/gdalinfo"
    )
    installed = root / "envs" / name / "bin/gdalinfo"
    source = Path(__file__).with_name("suspended_spawn.c")
    shutil.copy2(source, args.output / source.name)
    launcher = args.output / "suspended_spawn"
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
    cases = [
        (mode, operation, trial)
        for mode in ["hardlink", "copy"]
        for operation in [
            "none",
            "open-cache",
            "stat-cache",
            "open-cache-open-env",
            "open-cache-stat-env",
        ]
        for trial in range(20)
    ]
    random.Random(964).shuffle(cases)
    counts = collections.defaultdict(
        lambda: {"launches": 0, "failures": 0, "original_signature": 0}
    )
    with (args.output / "events.jsonl").open("w", buffering=1) as events:
        for mode, operation, trial in cases:
            installed.unlink()
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            started = time.time_ns()
            proc = subprocess.Popen(
                [
                    *command,
                    "run",
                    "-n",
                    name,
                    str(launcher),
                    operation,
                    str(cached),
                    str(installed),
                ],
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
            key = mode + "/" + operation
            event = {
                "event": "launch",
                "case": key,
                "trial": trial,
                "pid": proc.pid,
                "started_ns": started,
                "ended_ns": time.time_ns(),
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "original_signature": signature,
            }
            events.write(json.dumps(event) + "\n")
            if proc.returncode not in {0, 134} or not stdout.startswith(
                "suspended_child_pid="
            ):
                raise RuntimeError(f"Unexpected launcher result: {event}")
            snapshots = {
                "cache_app": fingerprint(cached),
                "env_app": fingerprint(installed),
            }
            assert snapshots["cache_app"]["sha256"] == snapshots["env_app"]["sha256"]
            events.write(
                json.dumps(
                    {"event": "files", "case": key, "trial": trial, "files": snapshots}
                )
                + "\n"
            )
            counts[key]["launches"] += 1
            counts[key]["failures"] += proc.returncode != 0
            counts[key]["original_signature"] += signature
            (args.output / "summary.json").write_text(
                json.dumps(counts, indent=2) + "\n"
            )
            if proc.returncode:
                print("FAIL", key, trial, stderr.strip(), flush=True)
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
