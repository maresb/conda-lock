#!/usr/bin/env python3
"""Test loader behavior while another process repeatedly opens cache hardlinks."""

import argparse
import collections
import json
import os
import platform
import random
import shutil
import subprocess

from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="Completed minimal_probe output; binaries are copied to a private cache",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    if platform.system() != "Darwin" or args.iterations < 1:
        parser.error("Requires macOS and positive iterations")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.fixture / "cache", root / "cache")
    shutil.copy2(args.fixture / "metadata.json", root / "fixture-metadata.json")
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "cache_scope": "fresh-inodes-per-case",
                "seed": 964,
                "iterations": args.iterations,
                "platform": platform.platform(),
                "reader_pause_nanoseconds": 50000,
            },
            indent=2,
        )
        + "\n"
    )
    subprocess.run(
        [
            "xcrun",
            "clang",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(Path(__file__).with_name("cache_reader.c")),
            "-o",
            str(root / "reader"),
        ],
        check=True,
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    counts = collections.defaultdict(lambda: {"launches": 0, "failures": 0})
    rng = random.Random(964)
    cases = [
        (mode, activity, iteration)
        for mode in ["hardlink", "executable", "library", "copy"]
        for activity in ["none", "executable", "library", "both"]
        for iteration in range(args.iterations)
    ]
    rng.shuffle(cases)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for number, (mode, activity, iteration) in enumerate(cases):
            case_root = root / "cases" / f"{number:04d}"
            shutil.copytree(root / "cache", case_root / "cache")
            prefix = case_root / "env"
            (prefix / "bin").mkdir(parents=True)
            (prefix / "lib").mkdir()
            cache_app = case_root / "cache/app/bin/app"
            cache_lib = case_root / "cache/outer/lib/libouter.dylib"
            for source, target, copy in [
                (cache_app, prefix / "bin/app", mode in ["executable", "copy"]),
                (cache_lib, prefix / "lib/libouter.dylib", mode in ["library", "copy"]),
                (
                    case_root / "cache/inner/lib/libinner.dylib",
                    prefix / "lib/libinner.dylib",
                    True,
                ),
            ]:
                (shutil.copy2 if copy else os.link)(source, target)
            sources = {
                "none": [],
                "executable": [cache_app],
                "library": [cache_lib],
                "both": [cache_app, cache_lib],
            }[activity]
            reader = None
            try:
                if sources:
                    reader = subprocess.Popen(
                        [str(root / "reader"), *map(str, sources)],
                        stdout=subprocess.PIPE,
                        text=True,
                    )
                    assert reader.stdout is not None
                    assert reader.stdout.readline().strip() == "ready"
                result = subprocess.run(
                    [str(prefix / "bin/app")], env=env, text=True, capture_output=True
                )
            finally:
                if reader is not None:
                    reader.terminate()
                    reader.wait(timeout=10)
                    assert reader.stdout is not None
                    reader.stdout.close()
            key = mode + "/" + activity
            counts[key]["launches"] += 1
            counts[key]["failures"] += result.returncode != 0
            events.write(
                json.dumps(
                    {
                        "case": key,
                        "iteration": iteration,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "files": {
                            str(p.relative_to(case_root)): {
                                "inode": p.stat().st_ino,
                                "nlink": p.stat().st_nlink,
                            }
                            for p in [
                                cache_app,
                                cache_lib,
                                prefix / "bin/app",
                                prefix / "lib/libouter.dylib",
                            ]
                        },
                    }
                )
                + "\n"
            )
            shutil.rmtree(case_root)
            (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
            if result.returncode:
                print("FAIL", key, result.stderr[:400], flush=True)
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
