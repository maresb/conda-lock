#!/usr/bin/env python3
"""Run the exited-thread reproducer on the host volume and on HFS+ and APFS images.

Run: python3 image_probe.py --output /tmp/dyld-images
Requires hdiutil, Xcode Command Line Tools, and adjacent reproduce_thread_exit.py.
"""

import argparse
import json
import shutil
import subprocess
import sys

from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    reproducer = Path(__file__).with_name("reproduce_thread_exit.py")
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
                    hdiutil = ["hdiutil", "create", "-size", "128m", "-fs", filesystem]
                    subprocess.run(
                        [*hdiutil, "-volname", label, str(image)],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                    root.mkdir()
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
                subprocess.run(
                    [
                        sys.executable,
                        str(reproducer),
                        "--output",
                        str(root / "probe"),
                        "--trials",
                        str(args.trials),
                        "--modes",
                        "hardlink,copy",
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=600,
                )
                summaries[label] = json.loads((root / "probe/summary.json").read_text())
                (output / (label + "-summary.json")).write_text(
                    json.dumps(summaries[label], indent=2) + "\n"
                )
                shutil.copy2(
                    root / "probe/events.jsonl", output / (label + "-events.jsonl")
                )
                mount = subprocess.run(
                    ["mount"], capture_output=True, text=True, check=False
                )
                log.write(mount.stdout + mount.stderr)
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
