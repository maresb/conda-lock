#!/usr/bin/env python3
"""Time hardlinking, cloning, and copying a package-like tree on the host volume.

Run: python3 link_cost_probe.py --output /tmp/dyld-link-cost
"""

import argparse
import ctypes
import ctypes.util
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--files", type=int, default=3000)
    parser.add_argument("--size", type=int, default=32 * 1024)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / "src"
    for i in range(args.files):
        path = source / f"d{i % 50}" / f"f{i}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(os.urandom(args.size))
    files = sorted(p for p in source.rglob("*") if p.is_file())

    def hardlink(target):
        for p in files:
            q = target / p.relative_to(source)
            q.parent.mkdir(parents=True, exist_ok=True)
            os.link(p, q)

    def clone(target):
        subprocess.run(["cp", "-Rc", str(source), str(target)], check=True)

    def copy(target):
        subprocess.run(["cp", "-R", str(source), str(target)], check=True)

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    libc.clonefile.restype = ctypes.c_int

    def clone_per_file(target):
        """Per-file clonefile(2) from Python, comparable to the os.link loop."""
        for p in files:
            q = target / p.relative_to(source)
            q.parent.mkdir(parents=True, exist_ok=True)
            if libc.clonefile(os.fsencode(p), os.fsencode(q), 0):
                raise OSError(ctypes.get_errno(), "clonefile", str(q))

    def copy_per_file(target):
        for p in files:
            q = target / p.relative_to(source)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, q)

    results = {}
    for name, action in [
        ("hardlink", hardlink),
        ("clone_tree", clone),
        ("copy_tree", copy),
        ("clone_per_file", clone_per_file),
        ("copy_per_file", copy_per_file),
    ]:
        seconds = []
        for round_ in range(args.rounds):
            target = root / f"{name}-{round_}"
            started = time.perf_counter()
            action(target)
            seconds.append(time.perf_counter() - started)
            sample = target / files[0].relative_to(source)
            shared = os.stat(sample).st_ino == os.stat(files[0]).st_ino
            assert shared == (name == "hardlink"), (name, shared)
            shutil.rmtree(target)
        results[name] = {
            "files": args.files,
            "bytes_per_file": args.size,
            "rounds": args.rounds,
            "median_seconds": round(statistics.median(seconds), 4),
            "min_seconds": round(min(seconds), 4),
            "max_seconds": round(max(seconds), 4),
        }
    shutil.rmtree(source)
    (root / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
