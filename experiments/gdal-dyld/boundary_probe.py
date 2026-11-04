#!/usr/bin/env python3
"""Locate alias changes around dyld startup, including silent wrong-library loads."""

import argparse
import collections
import json
import os
import random
import shutil
import subprocess

from pathlib import Path

from trigger_probe import fingerprint


APP = r"""
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>
extern int answer(void);
int main(int argc, char **argv, char **env, char **apple) {
    (void)argc; (void)env;
    char path[4096]; uint32_t size = sizeof(path);
    if (_NSGetExecutablePath(path, &size)) return 2;
    printf("dyld_path=%s\nargv0=%s\nanswer=%d\n", path, argv[0], answer());
    for (const char **p = (const char **)apple; *p; ++p)
        if (!strncmp(*p, "executable_path=", 16) || !strncmp(*p, "executable_file=", 16))
            printf("kernel_%s\n", *p);
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Requires this experiment's authorized GitHub runner")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    launcher = output / "boundary_spawn"
    source = Path(__file__).with_name("boundary_spawn.c")
    shutil.copy2(source, output / source.name)
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
    roots = [output / "root/cache", output / "root/env-a", output / "root/env-b"]
    for root in roots:
        (root / "bin").mkdir(parents=True)
        (root / "lib").mkdir()
    for root, answer in zip(roots[1:], [42, 99]):
        subprocess.run(
            [
                "xcrun",
                "clang",
                "-x",
                "c",
                "-",
                "-dynamiclib",
                "-Wl,-install_name,@rpath/libanswer.dylib",
                "-o",
                str(root / "lib/libanswer.dylib"),
            ],
            input=f"int answer(void) {{ return {answer}; }}\n",
            text=True,
            check=True,
        )
    cached, installed, other = [root / "bin/gdalinfo" for root in roots]
    (output / "identity_app.c").write_text(APP)
    subprocess.run(
        [
            "xcrun",
            "clang",
            "-x",
            "c",
            "-",
            "-L" + str(roots[1] / "lib"),
            "-lanswer",
            "-Wl,-rpath,@loader_path/../lib",
            "-o",
            str(cached),
        ],
        input=APP,
        text=True,
        check=True,
    )
    os.link(cached, other)
    operations = [
        "none",
        "pre-stat-alias",
        "stat-alias",
        "stat-env",
        "stat-alias-stat-env",
        "stat-alias-open-env",
        "stat-alias-fstat-env",
    ]
    cases = [
        (mode, alias, op, 0, trial)
        for mode in ["hardlink", "copy"]
        for alias in ["cache", "other-env"]
        for op in operations
        for trial in range(20)
    ]
    cases += [
        ("hardlink", "other-env", "stat-alias", delay, trial)
        for delay in [100000, 1000000, 2000000]
        for trial in range(10)
    ]
    random.Random(965).shuffle(cases)
    counts = collections.defaultdict(collections.Counter)
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    with (output / "events.jsonl").open("w", buffering=1) as events:
        for mode, alias, op, delay, trial in cases:
            installed.unlink(missing_ok=True)
            (os.link if mode == "hardlink" else shutil.copy2)(cached, installed)
            result = subprocess.run(
                [
                    str(launcher),
                    op,
                    str(cached if alias == "cache" else other),
                    str(installed),
                    str(delay),
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
            )
            values = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            key = f"{mode}/{alias}/{op}/{delay}"
            event = {
                "event": "launch",
                "case": key,
                "trial": trial,
                "returncode": result.returncode,
                "values": values,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            events.write(json.dumps(event) + "\n")
            if result.returncode not in {0, 134} or "pre_resume_id" not in values:
                raise RuntimeError(event)
            if (
                result.returncode
                and "Library not loaded: @rpath/libanswer.dylib" not in result.stderr
            ):
                raise RuntimeError(event)
            counts[key]["launches"] += 1
            counts[key]["failures"] += result.returncode != 0
            counts[key]["wrong_answer"] += values.get("answer") == "99"
            counts[key]["right_answer"] += values.get("answer") == "42"
            counts[key]["pre_resume_env"] += values["pre_resume_id"] == str(installed)
            counts[key]["pre_resume_alias"] += values["pre_resume_id"] == str(
                cached if alias == "cache" else other
            )
            (output / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")
        events.write(
            json.dumps(
                {
                    "event": "files",
                    "files": {
                        str(p): fingerprint(p) for p in [cached, installed, other]
                    },
                }
            )
            + "\n"
        )
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
