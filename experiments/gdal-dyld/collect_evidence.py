#!/usr/bin/env python3
"""Collect probe outputs without package caches or installed environments."""

import hashlib
import json
import os
import shutil
import sys

from pathlib import Path


root = Path(sys.argv[1])
output = root / "evidence"
output.mkdir(parents=True, exist_ok=True)
rows = []


def cells(data, prefix=""):
    """Yield (name, cell) for every dict of integer counts, including nested ones."""
    if not isinstance(data, dict):
        return
    if data and all(isinstance(v, (int, float)) for v in data.values()):
        yield prefix, data
        return
    for key, value in data.items():
        yield from cells(value, f"{prefix}/{key}" if prefix else key)


for entry in sorted(root.iterdir()):
    if entry.name in {"evidence", "root", "bin"}:
        continue
    candidates = [entry] if entry.is_file() else sorted(entry.rglob("*"))
    for path in candidates:
        if path.is_file() and path.suffix in {".json", ".jsonl", ".log", ".c"}:
            if path.suffix == ".jsonl" and path.stat().st_size > 50_000_000:
                continue
            target = output / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    summary = entry / "summary.json"
    if entry.is_dir() and summary.exists():
        for name, cell in cells(json.loads(summary.read_text())):
            counts = ", ".join(f"{k}={v}" for k, v in cell.items())
            rows.append(f"| {entry.name} | {name} | {counts} |")
manifest = {
    str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(output.rglob("*"))
    if p.is_file()
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(
            "\n| Probe | Cell | Counts |\n|---|---|---|\n" + "\n".join(rows) + "\n"
        )
