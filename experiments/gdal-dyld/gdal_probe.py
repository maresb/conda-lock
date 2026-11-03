#!/usr/bin/env python3
"""Compare file-copy interventions with the original GDAL package set on macOS."""

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import time

from pathlib import Path


def copy_file(path):
    """Break a hardlink without altering bytes, permissions, or symlink targets."""
    path = path.resolve()
    temporary = path.with_name(path.name + ".probe-copy")
    shutil.copy2(path, temporary)
    os.replace(temporary, path)


def snapshot(path):
    real = path.resolve()
    info = real.stat()
    return {
        "path": str(path),
        "realpath": str(real),
        "device": info.st_dev,
        "inode": info.st_ino,
        "nlink": info.st_nlink,
        "sha256": hashlib.sha256(real.read_bytes()).hexdigest(),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micromamba", type=Path, required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--root-prefix", type=Path, help="Reuse an existing private experiment cache"
    )
    parser.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Skip additional launches and file lookups after each measured sequence",
    )
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--launches", type=int, default=10)
    parser.add_argument(
        "--modes", nargs="+", default=["hardlink", "executable", "library", "copy"]
    )
    parser.add_argument("--sequences", nargs="+", type=int, default=[1, 3])
    parser.add_argument(
        "--original-formats",
        action="store_true",
        help="For a three-environment sequence, use unified, explicit, then env YAML",
    )
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("This experiment requires macOS")
    if min(args.trials, args.launches) < 1 or not set(args.sequences) <= {1, 3}:
        parser.error("Use positive trials/launches and sequences 1 and/or 3")
    if not set(args.modes) <= {"hardlink", "executable", "library", "copy"}:
        parser.error("Unknown copy intervention")
    if args.original_formats and args.sequences != [3]:
        parser.error("--original-formats requires --sequences 3")
    return args


def main():
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = args.root_prefix.resolve() if args.root_prefix else output / "root"
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("CONDA_", "MAMBA_", "DYLD_")):
            del env[key]
    command = [str(args.micromamba.resolve()), "--no-rc", "--no-env", "-r", str(root)]
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sw_vers": subprocess.check_output(["sw_vers"], text=True),
        "micromamba": subprocess.check_output(
            [*command, "--version"], env=env, text=True
        ).strip(),
        "lock_sha256": hashlib.sha256(args.lockfile.read_bytes()).hexdigest(),
        "seed": 964,
        "args": {
            k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
        },
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    cases = [
        (mode, sequence, trial)
        for mode in args.modes
        for sequence in args.sequences
        for trial in range(args.trials)
    ]
    random.Random(964).shuffle(cases)
    counts = {}
    with (output / "events.jsonl").open("w", buffering=1) as events:
        for case_no, (mode, sequence, trial) in enumerate(cases):
            label = f"{case_no:03d}-{mode}-{sequence}-{trial}"
            prefixes = []
            print("CREATE " + label, flush=True)
            for index in range(sequence):
                prefix = (
                    (output if args.root_prefix else root)
                    / "envs"
                    / (f"case-{case_no:03d}-{index}")
                )
                lockfile = args.lockfile.resolve()
                if args.original_formats:
                    lockfile = [
                        lockfile.with_name("conda-lock.yml"),
                        lockfile,
                        lockfile.with_name("conda-osx-arm64.lock.yml"),
                    ][index]
                create = [
                    *command,
                    "create",
                    "-y",
                    "-p",
                    str(prefix),
                    "-f",
                    str(lockfile),
                ]
                if mode == "copy":
                    create.append("--always-copy")
                start = time.monotonic()
                started_ns = time.time_ns()
                with (output / (label + f"-create-{index}.log")).open("w") as log:
                    process = subprocess.Popen(
                        create,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    returncode = process.wait()
                    if returncode:
                        raise subprocess.CalledProcessError(returncode, create)
                if mode == "executable":
                    copy_file(prefix / "bin/gdalinfo")
                elif mode == "library":
                    copy_file(prefix / "lib/libgdal.dylib")
                events.write(
                    json.dumps(
                        {
                            "event": "create",
                            "case": label,
                            "index": index,
                            "seconds": time.monotonic() - start,
                            "started_ns": started_ns,
                            "ended_ns": time.time_ns(),
                            "pid": process.pid,
                            "prefix": str(prefix),
                        }
                    )
                    + "\n"
                )
                prefixes.append(prefix)
            # First launches occur before stat/hash diagnostics, to avoid warming file paths.
            # Round zero preserves the CI order: first, second, then third environment.
            for launch in range(args.launches):
                for index, prefix in enumerate(prefixes):
                    started_ns = time.time_ns()
                    process = subprocess.Popen(
                        [*command, "run", "-p", str(prefix), "gdalinfo", "--version"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    stdout, stderr = process.communicate()
                    result = subprocess.CompletedProcess(
                        process.args, process.returncode, stdout, stderr
                    )
                    ended_ns = time.time_ns()
                    key = mode + "/" + str(sequence)
                    tally = counts.setdefault(
                        key, {"launches": 0, "failures": 0, "cases": []}
                    )
                    tally["launches"] += 1
                    tally["failures"] += result.returncode != 0
                    if label not in tally["cases"]:
                        tally["cases"].append(label)
                    events.write(
                        json.dumps(
                            {
                                "event": "launch",
                                "case": label,
                                "mode": mode,
                                "sequence": sequence,
                                "index": index,
                                "launch": launch,
                                "returncode": result.returncode,
                                "stdout": result.stdout,
                                "stderr": result.stderr,
                                "started_ns": started_ns,
                                "ended_ns": ended_ns,
                                "pid": process.pid,
                            }
                        )
                        + "\n"
                    )
                    if result.returncode:
                        print(
                            f"FAIL {label} env={index} launch={launch}: {result.stderr.strip()}",
                            flush=True,
                        )
            # Collect detailed loader traces only after the uninstrumented launches.
            for index, prefix in enumerate([] if args.skip_diagnostics else prefixes):
                traces = subprocess.run(
                    [
                        *command,
                        "run",
                        "-p",
                        str(prefix),
                        "env",
                        "DYLD_PRINT_LIBRARIES=1",
                        "DYLD_PRINT_RPATHS=1",
                        "gdalinfo",
                        "--version",
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                (output / (label + f"-trace-{index}.log")).write_text(traces.stdout)
                files = [
                    snapshot(prefix / "bin/gdalinfo"),
                    snapshot(prefix / "lib/libgdal.dylib"),
                    snapshot(prefix / "lib/libcrypto.3.dylib"),
                ]
                events.write(
                    json.dumps(
                        {
                            "event": "files",
                            "case": label,
                            "index": index,
                            "files": files,
                        }
                    )
                    + "\n"
                )
            # Use the package manager to also unregister the temporary environments.
            for index, prefix in enumerate(prefixes):
                with (output / (label + f"-remove-{index}.log")).open("w") as log:
                    subprocess.run(
                        [*command, "env", "remove", "-y", "-p", str(prefix)],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
            (output / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
            print("DONE " + label + " " + json.dumps(counts), flush=True)
        for cached in (
            []
            if args.skip_diagnostics
            else sorted((root / "pkgs").rglob("libgdal.32.3.6.2.dylib"))
        ):
            events.write(
                json.dumps({"event": "cache", "file": snapshot(cached)}) + "\n"
            )


if __name__ == "__main__":
    main()
