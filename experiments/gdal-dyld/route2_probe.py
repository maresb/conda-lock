#!/usr/bin/env python3
"""One cache-alias lookup between spawn and dyld startup, per filesystem.

The parent spawns the identity app suspended, performs one lookup, resumes it,
and records which alias dyld chose. Runs on the host volume and on APFS and
HFS+ disk images, with fresh inodes per trial.

Run: python3 route2_probe.py --output /tmp/dyld-route2
Requires hdiutil, Xcode Command Line Tools, and adjacent suspended_spawn.c and
reproduce_thread_exit.py.
"""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess
import sys

from pathlib import Path

from reproduce_thread_exit import APP


def run_cells(launcher, template, root, trials, events):
    (root / "cache").mkdir()
    (root / "env").mkdir()
    cached, installed = root / "cache/app", root / "env/app"
    cases = [
        (mode, operation, trial)
        for mode in ["hardlink", "copy"]
        for operation in ["none", "stat-cache", "open-cache", "open-cache-stat-env"]
        for trial in range(trials)
    ]
    random.Random(972).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    for mode, operation, trial in cases:
        installed.unlink(missing_ok=True)
        cached.unlink(missing_ok=True)
        shutil.copy2(template, cached)
        (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
        result = subprocess.run(
            [str(launcher), operation, str(cached), str(installed)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=10,
        )
        values = dict(s.split("=", 1) for s in result.stdout.splitlines() if "=" in s)
        assert values["launch_path"] == str(installed), values
        assert values["main_image"] in {str(cached), str(installed)}, values
        key = f"{mode}/{operation}"
        counts[key]["launches"] += 1
        counts[key]["cache_path"] += values["main_image"] == str(cached)
        counts[key]["env_path"] += values["main_image"] == str(installed)
        events.write(
            json.dumps(
                {
                    "event": "launch",
                    "filesystem_root": str(root),
                    "case": key,
                    "trial": trial,
                    "returncode": result.returncode,
                    "values": values,
                    "stderr": result.stderr,
                }
            )
            + "\n"
        )
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("suspended_spawn.c")
    shutil.copy2(source, output / source.name)
    launcher, template = output / "suspended_spawn", output / "template"
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
    (output / "identity_app.c").write_text(APP)
    subprocess.run(
        ["xcrun", "clang", "-x", "c", "-", "-o", str(template)],
        input=APP,
        text=True,
        check=True,
    )
    summaries = {}
    with (output / "events.jsonl").open("w", buffering=1) as events:
        for label, filesystem in [
            ("host-apfs", None),
            ("image-apfs", "APFS"),
            ("image-hfs", "HFS+"),
        ]:
            root = output / label
            mounted = False
            with (output / (label + ".log")).open("w") as log:
                try:
                    root.mkdir()
                    if filesystem:
                        image = output / (label + ".dmg")
                        subprocess.run(
                            [
                                "hdiutil",
                                "create",
                                "-size",
                                "64m",
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
                    (root / ".metadata_never_index").touch()
                    # Fresh copies of the binaries on each volume keep every trial local to it.
                    volume_template = root / "template"
                    shutil.copy2(template, volume_template)
                    summaries[label] = run_cells(
                        launcher, volume_template, root, args.trials, events
                    )
                    mount = subprocess.run(
                        ["mount"], capture_output=True, text=True, check=False
                    )
                    log.write(mount.stdout)
                finally:
                    if mounted:
                        subprocess.run(
                            ["hdiutil", "detach", str(root)],
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            check=False,
                        )
                        image.unlink(missing_ok=True)
    (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
