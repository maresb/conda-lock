#!/usr/bin/env python3
"""Connect the cache-access reproducer to the original GDAL package and sequence."""

import argparse
import collections
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time

from pathlib import Path


ORIGINAL_UUID = "042BC0C2-C636-39C6-8DFD-3580A4847EF8"


def fingerprint(path):
    info = path.stat()
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "nlink": info.st_nlink,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["natural", "readers"])
    parser.add_argument("--micromamba", type=Path, required=True)
    parser.add_argument("--root-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument(
        "--reader-backend", choices=["syscalls", "spotlight"], default="syscalls"
    )
    args = parser.parse_args()
    if (
        platform.system() != "Darwin"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Run only on this experiment's authorized GitHub macOS runner")
    if args.trials < 1:
        parser.error("Use positive trials")
    return args


def activities_for(backend):
    if backend == "spotlight":
        return [(op, "app") for op in ["none", "import", "test"]]
    return [("none", "app")] + [
        (op, target)
        for op in ["open", "stat", "getattrlist", "event"]
        for target in ["app", "lib"]
    ]


def reader_command(operation, target, binary, log_path):
    if operation in {"import", "test"}:
        return [
            sys.executable,
            str(Path(__file__).with_name("spotlight_reader.py")),
            operation,
            str(target),
            str(log_path),
        ]
    return [str(binary), operation, str(target)]


def main():
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = args.root_prefix.resolve()
    command = [str(args.micromamba), "-r", str(root)]
    fixtures = Path(__file__).resolve().parent / "fixtures"
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    metadata = {
        "platform": platform.platform(),
        "trials": args.trials,
        "mode": args.mode,
        "reader_backend": args.reader_backend,
        "micromamba": subprocess.check_output(
            [*command, "--version"], text=True
        ).strip(),
        "root_prefix": str(root),
        "seed": 964,
        "original_error_uuid": ORIGINAL_UUID,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    counts = collections.defaultdict(
        lambda: {"launches": 0, "failures": 0, "original_signature": 0}
    )

    with (output / "events.jsonl").open("w", buffering=1) as events:

        def record(event):
            events.write(json.dumps(event) + "\n")

        def run_logged(arguments, label):
            started = time.time_ns()
            with (output / (label + ".log")).open("w") as log:
                proc = subprocess.Popen(
                    [*command, *arguments],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                rc = proc.wait(timeout=240)
            record(
                {
                    "event": "command",
                    "label": label,
                    "command": arguments,
                    "pid": proc.pid,
                    "started_ns": started,
                    "ended_ns": time.time_ns(),
                    "returncode": rc,
                }
            )
            if rc:
                raise RuntimeError(f"{label} failed; inspect log")

        def launch(name, case, trial, retry=False):
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
            result = {
                "event": "launch",
                "case": case,
                "trial": trial,
                "name": name,
                "retry": retry,
                "pid": proc.pid,
                "started_ns": started,
                "ended_ns": time.time_ns(),
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "original_signature": signature,
            }
            record(result)
            if not retry:
                cell = counts[case]
                cell["launches"] += 1
                cell["failures"] += proc.returncode != 0
                cell["original_signature"] += signature
                (output / "summary.json").write_text(
                    json.dumps(counts, indent=2) + "\n"
                )
            if proc.returncode:
                print("FAIL", case, trial, stderr.strip(), flush=True)
            return result

        def files(name):
            prefix = root / "envs" / name
            cached = list(
                (root / "pkgs").glob("**/libgdal-3.6.2-h51eea9d_5/bin/gdalinfo")
            )
            if len(cached) != 1:
                raise RuntimeError(f"Expected one cached gdalinfo, found {cached}")
            cache_app = cached[0]
            cache_lib = cache_app.parent.parent / "lib/libgdal.32.3.6.2.dylib"
            return {
                "cache_app": cache_app,
                "env_app": prefix / "bin/gdalinfo",
                "cache_lib": cache_lib,
                "env_lib": prefix / "lib/libgdal.32.3.6.2.dylib",
            }

        if args.mode == "natural":
            names = ["gdal-test-mm-lock", "gdal-test-mm-explicit", "gdal-test-mm-env"]
            locks = [
                "conda-lock.yml",
                "conda-osx-arm64.lock",
                "conda-osx-arm64.lock.yml",
            ]
            for trial in range(args.trials):
                print("CREATE", trial, flush=True)
                for name, lock in zip(names, locks):
                    run_logged(
                        ["create", "-y", "-n", name, "-f", str(fixtures / lock)],
                        f"{trial:03d}-create-{name}",
                    )
                # No filesystem diagnostics or repeated successful launches before these three.
                results = [launch(name, name, trial) for name in names]
                for name, result in zip(names, results):
                    if result["returncode"]:
                        launch(name, name, trial, retry=True)
                    record(
                        {
                            "event": "files",
                            "trial": trial,
                            "name": name,
                            "files": {
                                k: fingerprint(p) for k, p in files(name).items()
                            },
                        }
                    )
                for name in names:
                    run_logged(
                        ["env", "remove", "-y", "-n", name],
                        f"{trial:03d}-remove-{name}",
                    )
                print("DONE", trial, json.dumps(counts), flush=True)
        else:
            name = "gdal-trigger-reader"
            run_logged(
                [
                    "create",
                    "-y",
                    "-n",
                    name,
                    "-f",
                    str(fixtures / "conda-osx-arm64.lock"),
                ],
                "create",
            )
            paths = files(name)
            initial = {k: fingerprint(p) for k, p in paths.items()}
            record({"event": "initial_files", "files": initial})
            assert initial["cache_app"]["inode"] == initial["env_app"]["inode"]
            assert initial["cache_lib"]["inode"] != initial["env_lib"]["inode"]
            source = Path(__file__).with_name("metadata_reader.c")
            shutil.copy2(source, output / source.name)
            reader_binary = output / "metadata_reader"
            subprocess.run(
                [
                    "xcrun",
                    "clang",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(source),
                    "-o",
                    str(reader_binary),
                ],
                check=True,
            )
            activities = activities_for(args.reader_backend)
            cases = [
                (mode, op, target, trial)
                for mode in ["hardlink", "copy"]
                for op, target in activities
                for trial in range(args.trials)
            ]
            random.Random(964).shuffle(cases)
            for mode, operation, target, trial in cases:
                # rename(source, destination) is a no-op when both name the same inode.
                # No measured process is running while this fixture is replaced.
                paths["env_app"].unlink()
                (os.link if mode == "hardlink" else shutil.copy2)(
                    paths["cache_app"], paths["env_app"]
                )
                key = f"{mode}/{target}/{operation}"
                reader = None
                operations = 0
                try:
                    if operation != "none":
                        reader = subprocess.Popen(
                            reader_command(
                                operation,
                                paths["cache_" + target],
                                reader_binary,
                                output / f"{mode}-{operation}-{trial:03d}.log",
                            ),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        assert reader.stdout is not None
                        assert reader.stdout.readline().strip() == "ready"
                    result = launch(name, key, trial)
                finally:
                    if reader is not None:
                        reader.terminate()
                        stdout, stderr = reader.communicate(timeout=15)
                        assert reader.returncode == 0, stderr
                        operations = int(stdout.strip())
                        assert operations > 0
                # A retry is a separate observation, never included in the primary denominator.
                retry = (
                    launch(name, key, trial, retry=True)
                    if result["returncode"]
                    else None
                )
                current = {k: fingerprint(p) for k, p in paths.items()}
                assert current["env_app"]["sha256"] == initial["cache_app"]["sha256"]
                assert current["env_lib"] == initial["env_lib"]
                assert current["cache_lib"] == initial["cache_lib"]
                record(
                    {
                        "event": "reader_result",
                        "case": key,
                        "trial": trial,
                        "reader_operations": operations,
                        "files": current,
                        "retry_returncode": retry["returncode"] if retry else None,
                    }
                )
            print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
