#!/usr/bin/env python3
"""Compare hardlink alias selection across actors and filesystems on CI."""

import argparse
import collections
import json
import os
import shutil
import subprocess

from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", choices=["alias", "origin"], default="alias")
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Requires this experiment's authorized GitHub runner")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name(args.probe + "_state.c")
    shutil.copy2(source, output / source.name)
    binary = output / "alias_state"
    subprocess.run(
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
        check=True,
    )
    summaries = {}
    for label, filesystem in [
        ("host-apfs", None),
        ("image-apfs", "APFS"),
        ("image-hfs", "HFS+"),
    ]:
        root = output / label
        mounted = False
        with (output / (label + ".log")).open("w") as log:
            try:
                if filesystem:
                    image = output / (label + ".dmg")
                    subprocess.run(
                        [
                            "hdiutil",
                            "create",
                            "-size",
                            "128m",
                            "-fs",
                            filesystem,
                            "-volname",
                            label,
                            str(image),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                    subprocess.run(
                        [
                            "hdiutil",
                            "attach",
                            "-nobrowse",
                            "-mountpoint",
                            str(root),
                            str(image),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                    mounted = True
                else:
                    root.mkdir()
                (root / ".metadata_never_index").touch()
                (root / "cache").mkdir()
                (root / "env").mkdir()
                cached, installed = root / "cache/file", root / "env/file"
                cached.write_text("This is data, not a Mach-O executable.\n")
                os.link(cached, installed)
                result = subprocess.run(
                    [str(binary), str(cached), str(installed)],
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=180,
                )
                (output / (label + ".jsonl")).write_text(result.stdout)
                log.write(result.stderr)
                rows = [json.loads(s) for s in result.stdout.splitlines()]
                counts = collections.Counter(
                    (
                        e["actor"],
                        e["operation"],
                        e["target"],
                        e["before"],
                        e["actor_path"],
                        e["parent_fd"],
                        e["parent_id"],
                    )
                    for e in rows
                    if e["event"] == "lookup"
                )
                summaries[label] = {
                    "identity": rows[0],
                    "counts": [
                        {"key": k, "count": v} for k, v in sorted(counts.items())
                    ],
                }
                if args.probe == "origin":
                    counts = collections.Counter(
                        (
                            e["workers"],
                            e["before"],
                            e["parent_fd"],
                            e["parent_id"],
                            e["cache_linkid_path"],
                            e["env_linkid_path"],
                        )
                        for e in rows
                        if e["event"] == "origin"
                    )
                    summaries[label] = {
                        "identities": rows[:3],
                        "counts": [
                            {"key": k, "count": v} for k, v in sorted(counts.items())
                        ],
                    }
                (output / "summary.json").write_text(
                    json.dumps(summaries, indent=2) + "\n"
                )
                print(label, rows[0], "lookups", len(rows) - 1, flush=True)
            finally:
                if mounted:
                    subprocess.run(
                        ["hdiutil", "detach", str(root)],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )


if __name__ == "__main__":
    main()
