#!/usr/bin/env python3
"""Run a serial stale-origin sequence against the original GDAL executable."""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess

from pathlib import Path

from trigger_probe import ORIGINAL_UUID, fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micromamba", type=Path, required=True)
    parser.add_argument("--root-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prime", action="store_true")
    parser.add_argument("--lifecycle", action="store_true")
    args = parser.parse_args()
    if args.lifecycle:
        args.prime = True
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Requires this experiment's authorized GitHub runner")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = args.root_prefix
    name = "gdal-sequence"
    command = [str(args.micromamba), "-r", str(root)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    lock = Path(__file__).with_name("fixtures") / "conda-osx-arm64.lock"
    with (output / "create.log").open("w") as log:
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
    source = Path(__file__).with_name("prime_exec.c" if args.prime else "stale_exec.c")
    shutil.copy2(source, output / source.name)
    launcher = output / "stale_exec"
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
        (mode, state, method, op, trial)
        for mode in ["hardlink", "copy"]
        for state in ["self", "thread", "thread-self", "thread-bounce"]
        for method in ["probe", "exec", "spawn"]
        for op in ["stat", "open"]
        for trial in range(20)
    ]
    random.Random(966).shuffle(cases)
    if args.prime:
        cases = [
            (mode, state, method, str(workers), trial)
            for mode in ["hardlink", "copy"]
            for state in ["cache", "env"]
            for method in ["exec", "spawn"]
            for workers in ([0, 1, 8, 32] if mode == "hardlink" else [8])
            for trial in range(20)
        ]
        random.Random(967).shuffle(cases)
    if args.lifecycle:
        cases = [
            (mode, state, method, "1", trial)
            for mode in ["hardlink", "copy"]
            for state in ["cache-dead", "cache-alive", "env-dead", "env-alive"]
            for method in ["exec", "spawn"]
            for trial in range(40)
        ]
        random.Random(968).shuffle(cases)
    template = output / "original-gdalinfo"
    shutil.copy2(cached, template)
    counts = collections.defaultdict(collections.Counter)
    with (output / "events.jsonl").open("w", buffering=1) as events:
        for mode, state, method, op, trial in cases:
            if args.prime:
                # Fresh inode prevents earlier cells from priming this cell's origin cache.
                cached.unlink()
                shutil.copy2(template, cached)
            installed.unlink()
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            result = subprocess.run(
                [
                    *command,
                    "run",
                    "-n",
                    name,
                    str(launcher),
                    state,
                    str(cached),
                    str(installed),
                    method,
                    op,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            signature = (
                "Library not loaded: @rpath/libcrypto.3.dylib" in result.stderr
                and ORIGINAL_UUID in result.stderr
                and "/pkgs/" in result.stderr
            )
            key = f"{mode}/{state}/{method}/{op}"
            event = {
                "event": "lookup" if method == "probe" else "launch",
                "case": key,
                "trial": trial,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "original_signature": signature,
            }
            events.write(json.dumps(event) + "\n")
            if result.returncode not in {0, 134} or (
                result.returncode and not signature
            ):
                raise RuntimeError(event)
            counts[key]["launches"] += 1
            counts[key]["failures"] += result.returncode != 0
            counts[key]["original_signature"] += signature
            counts[key]["probe_cache"] += result.stdout.strip() == "resolved=" + str(
                cached
            )
            counts[key]["probe_env"] += result.stdout.strip() == "resolved=" + str(
                installed
            )
            (output / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
        events.write(
            json.dumps(
                {
                    "event": "files",
                    "files": {str(p): fingerprint(p) for p in [cached, installed]},
                }
            )
            + "\n"
        )
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
