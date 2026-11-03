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
output.mkdir(exist_ok=True)
rows = []
for entry in sorted(root.iterdir()):
    if entry.name in {"evidence", "root", "bin"}:
        continue
    candidates = [entry] if entry.is_file() else sorted(entry.iterdir())
    for path in candidates:
        if path.is_file() and path.suffix in {".json", ".jsonl", ".log", ".c"}:
            target = output / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    summary = entry / "summary.json"
    if entry.is_dir() and summary.exists():
        for key, cell in json.loads(summary.read_text()).items():
            if isinstance(cell, dict) and "launches" in cell:
                rows.append(
                    f"| {entry.name} | {key} | {cell['launches']} | {cell['failures']} | {cell.get('success_cache_path', '')} |"
                )
manifest = {
    str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(output.rglob("*"))
    if p.is_file()
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(
            "\n| Probe | Cell | Launches | Failures | Passing with cache path |\n|---|---|---:|---:|---:|\n"
            + "\n".join(rows)
            + "\n"
        )
