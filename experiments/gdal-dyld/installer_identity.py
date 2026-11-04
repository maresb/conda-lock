#!/usr/bin/env python3
"""Record whether an installed executable shares its inode with the package cache.

Run: python3 installer_identity.py --output DIR --label NAME --executable PATH \
    --cache-root DIR [--launches N]
The cache root is searched for files named like the executable's basename
under a bin directory.
"""

import argparse
import fcntl
import hashlib
import json
import os
import struct
import subprocess
import sys

from pathlib import Path


F_LOG2PHYS = 49  # macOS: physical device offset of the file's current logical offset


def physical_offset(path):
    """Device offset of the file's first block, or None if unavailable.

    Equal offsets for two files mean shared storage: a hardlink or a clone.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            raw = fcntl.fcntl(fd, F_LOG2PHYS, bytes(24))
        finally:
            os.close(fd)
        _flags, _contiguous, offset = struct.unpack("=I4xqq", raw)
        return offset
    except (OSError, struct.error):
        return None


def identity(path):
    st = os.stat(path)
    return {
        "path": str(path),
        "device": st.st_dev,
        "inode": st.st_ino,
        "nlink": st.st_nlink,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "physical_offset": physical_offset(path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--launches", type=int, default=20)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    args.output.mkdir(parents=True, exist_ok=True)
    executable = args.executable.resolve()
    name = executable.name
    cached = sorted(
        p
        for p in args.cache_root.rglob(name)
        if p.is_file() and p.parent.name == "bin" and not p.is_symlink()
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    launches = []
    for i in range(args.launches):
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        launches.append(
            {
                "launch": i,
                "returncode": result.returncode,
                "stdout": result.stdout[-300:],
                "stderr": result.stderr[-600:],
            }
        )
    installed = identity(executable)
    cached_identities = [identity(p) for p in cached]
    record = {
        "label": args.label,
        "installed": installed,
        "cached": cached_identities,
        "shares_inode_with_cache": any(
            c["inode"] == installed["inode"] and c["device"] == installed["device"]
            for c in cached_identities
        ),
        "shares_storage_with_cache": any(
            c["physical_offset"] is not None
            and c["physical_offset"] == installed["physical_offset"]
            for c in cached_identities
        ),
        "launches": len(launches),
        "failures": sum(1 for item in launches if item["returncode"] != 0),
        "events": launches,
    }
    (args.output / f"{args.label}.json").write_text(json.dumps(record, indent=2) + "\n")
    summary_path = args.output / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    summary[args.label] = {
        "launches": record["launches"],
        "failures": record["failures"],
        "shares_inode_with_cache": int(record["shares_inode_with_cache"]),
        "shares_storage_with_cache": int(record["shares_storage_with_cache"]),
        "nlink": installed["nlink"],
        "cache_matches": len(cached),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary[args.label]))


if __name__ == "__main__":
    main()
