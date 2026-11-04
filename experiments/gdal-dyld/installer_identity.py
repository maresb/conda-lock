#!/usr/bin/env python3
"""Record whether an installed executable shares its inode or storage with the package cache.

Run: python3 installer_identity.py --output DIR --label NAME --executable PATH \
    --cache-root DIR [--launches N]
     python3 installer_identity.py --output DIR --self-check
The cache root is searched for files named like the executable's basename
under a bin directory. Storage is compared extent by extent with the adjacent
log2phys.c helper; --self-check records a hardlink, a clone, and a copy of a
fresh file as controls.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

from pathlib import Path


def build_helper(output):
    """Compile log2phys.c into the output directory; None if that fails."""
    source = Path(__file__).with_name("log2phys.c")
    binary = output / "log2phys"
    if binary.exists():
        return binary
    shutil.copy2(source, output / source.name)
    result = subprocess.run(
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
        capture_output=True,
        text=True,
    )
    if result.returncode:
        (output / "log2phys-build.log").write_text(result.stdout + result.stderr)
        return None
    return binary


def extents(helper, path):
    """Physical extents of a file as (device_offset, length), plus completeness."""
    if helper is None:
        return {"extents": [], "complete": False, "struct_size": None}
    result = subprocess.run(
        [str(helper), str(path)], capture_output=True, text=True, timeout=60
    )
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or not lines or "size" not in lines[-1]:
        return {"extents": [], "complete": False, "struct_size": None}
    tail = lines.pop()
    return {
        "extents": [[e["device_offset"], e["length"]] for e in lines],
        "complete": bool(tail["complete"])
        and sum(e["length"] for e in lines) == tail["size"],
        "struct_size": tail["struct_size"],
    }


def shared_bytes(a, b):
    """Bytes of device storage that two extent lists have in common."""
    total = 0
    for a_off, a_len in a:
        for b_off, b_len in b:
            low, high = max(a_off, b_off), min(a_off + a_len, b_off + b_len)
            if high > low:
                total += high - low
    return total


def identity(helper, path):
    st = os.stat(path)
    return {
        "path": str(path),
        "device": st.st_dev,
        "inode": st.st_ino,
        "nlink": st.st_nlink,
        "size": st.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **extents(helper, path),
    }


def storage(installed, others):
    """Summary fields comparing one file's storage with a list of others."""
    complete = installed["complete"] and all(o["complete"] for o in others)
    shared = max(
        (shared_bytes(installed["extents"], o["extents"]) for o in others), default=0
    )
    return {
        "shares_inode_with_cache": int(
            any(
                o["inode"] == installed["inode"] and o["device"] == installed["device"]
                for o in others
            )
        ),
        "shares_storage_with_cache": int(shared > 0),
        "shared_bytes": shared,
        "size": installed["size"],
        "storage_complete": int(bool(others) and complete),
        "nlink": installed["nlink"],
    }


def write_summary(output, label, fields):
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    summary[label] = fields
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(label, json.dumps(fields))


def self_check(helper, output):
    """Measure a hardlink, a clonefile clone, and a byte copy of a fresh file."""
    control = output / "control"
    control.mkdir(exist_ok=True)
    original = control / "original"
    original.write_bytes(os.urandom(1 << 20))
    for name in ["hardlink", "clone", "copy"]:
        (control / name).unlink(missing_ok=True)
    os.link(original, control / "hardlink")
    subprocess.run(["cp", "-c", str(original), str(control / "clone")], check=True)
    shutil.copyfile(original, control / "copy")
    base = identity(helper, original)
    for name in ["hardlink", "clone", "copy"]:
        fields = storage(identity(helper, control / name), [base])
        fields.update({"launches": 0, "failures": 0, "cache_matches": 1})
        write_summary(output, f"control-{name}", fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--label")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--launches", type=int, default=20)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    args.output.mkdir(parents=True, exist_ok=True)
    helper = build_helper(args.output)
    if args.self_check:
        self_check(helper, args.output)
        return
    if not (args.label and args.executable and args.cache_root):
        parser.error("--label, --executable, and --cache-root are required")
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
    installed = identity(helper, executable)
    cached_identities = [identity(helper, p) for p in cached]
    fields = storage(installed, cached_identities)
    fields.update(
        {
            "launches": len(launches),
            "failures": sum(1 for item in launches if item["returncode"] != 0),
            "cache_matches": len(cached),
        }
    )
    record = {
        "label": args.label,
        "installed": installed,
        "cached": cached_identities,
        "summary": fields,
        "events": launches,
    }
    (args.output / f"{args.label}.json").write_text(json.dumps(record, indent=2) + "\n")
    write_summary(args.output, args.label, fields)


if __name__ == "__main__":
    main()
