#!/usr/bin/env python3
"""Spawn the hardlinked executable repeatedly from one process after a stale lookup.

If retries pass only because an intermediate process's thread takes the freed
identity, launches from the same long-lived process should keep choosing the
cache path.

Run: python3 respawn_probe.py --output /tmp/dyld-respawn
Requires Xcode Command Line Tools and adjacent respawn.c and reproduce_thread_exit.py.
"""

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys

from pathlib import Path

from reproduce_thread_exit import APP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=4)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Requires macOS")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name("respawn.c")
    shutil.copy2(source, root / source.name)
    launcher, template = root / "respawn", root / "template"
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
    (root / "identity_app.c").write_text(APP)
    subprocess.run(
        ["xcrun", "clang", "-x", "c", "-", "-o", str(template)],
        input=APP,
        text=True,
        check=True,
    )
    (root / "cache").mkdir()
    (root / "env").mkdir()
    cached, installed = root / "cache/app", root / "env/app"
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    counts = collections.defaultdict(collections.Counter)
    with (root / "events.jsonl").open("w", buffering=1) as events:
        for mode in ["hardlink", "copy"]:
            for trial in range(args.trials):
                installed.unlink(missing_ok=True)
                cached.unlink(missing_ok=True)
                shutil.copy2(template, cached)
                (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
                result = subprocess.run(
                    [str(launcher), str(cached), str(installed), str(args.repeats)],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=True,
                    timeout=20,
                )
                images = [
                    line.split("=", 1)[1]
                    for line in result.stdout.splitlines()
                    if line.startswith("main_image=")
                ]
                assert len(images) == args.repeats, result.stdout
                assert all(i in {str(cached), str(installed)} for i in images), images
                chosen = ["cache" if i == str(cached) else "env" for i in images]
                for index, choice in enumerate(chosen):
                    key = f"{mode}/launch{index + 1}"
                    counts[key]["launches"] += 1
                    counts[key]["cache_path"] += choice == "cache"
                    counts[key]["env_path"] += choice == "env"
                events.write(
                    json.dumps(
                        {
                            "event": "trial",
                            "case": mode,
                            "trial": trial,
                            "chosen": chosen,
                        }
                    )
                    + "\n"
                )
    (root / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
