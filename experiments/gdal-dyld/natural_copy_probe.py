#!/usr/bin/env python3
"""Real install sequence with only the executable copied, and with pauses before launch.

Three phases on one runner, all with micromamba 2.10.0 and the explicit GDAL
lockfile fixture:

census     A dedicated environment is created, every Mach-O file in it is
           matched by device and inode against the package cache, and the
           environment is removed, so the share of libraries that are hardlinked
           to the cache at all is known without touching a measured environment.
natural    Per trial: `micromamba create`, then one of five cells, shuffled:
           launch at once; sleep 1 s or 2 s first; or replace only bin/gdalinfo
           with a byte copy and launch at once, with or without
           DYLD_PRINT_LIBRARIES=1. Nothing else touches either alias between the
           create and the launch. One counted launch per trial, a retry recorded
           separately, fingerprints taken only after the launches, then
           `micromamba env remove`. The hardlink cells and the plain copy cell
           launch with no DYLD_ variables, like the earlier natural runs; the
           printing copy cell records the path dyld assigned to each library.
triggered  One environment. Per trial, a fresh cache inode for the target file,
           a finished process that looked up its cache alias (touch_exit), an
           optional pause, then a launcher that looks up the environment alias
           and spawns gdalinfo (prime_exec env-dead ... spawn 0): delay_probe.py's
           design with the real executable. Library cells copy the executable,
           trigger on the cache alias of one named hardlinked library that
           gdalinfo loads (up to three such libraries, each its own cell), and
           launch with DYLD_PRINT_LIBRARIES=1 to record where dyld placed it.

DYLD_PRINT_LIBRARIES is set only in cells whose outcome is library placement.
Its lines are grouped by process ID and only gdalinfo's own process is read, since
the launcher (micromamba or prime_exec) prints its own images too.
"""

import argparse
import collections
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import time

from pathlib import Path


ORIGINAL_UUID = "042BC0C2-C636-39C6-8DFD-3580A4847EF8"
SIGNATURE = "Library not loaded: @rpath/libcrypto.3.dylib"
MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
}
DYLD_LINE = re.compile(r"^dyld\[(\d+)\]: <[0-9A-F-]+> (.+)$")


def fingerprint(path):
    info = path.stat()
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "nlink": info.st_nlink,
        "size": info.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def is_macho(path):
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def dyld_processes(stderr):
    """Process ID -> image paths in load order, from DYLD_PRINT_LIBRARIES lines."""
    processes = collections.OrderedDict()
    for line in stderr.splitlines():
        match = DYLD_LINE.match(line)
        if match:
            processes.setdefault(match.group(1), []).append(match.group(2))
    return processes


def gdal_images(stderr):
    """gdalinfo's own images; the first is its main executable. None if not found."""
    groups = [
        images
        for images in dyld_processes(stderr).values()
        if images and Path(images[0]).name == "gdalinfo"
    ]
    if len(groups) != 1:
        return None
    return groups[0]


def archive_stderr(output, key, trial, retry, stderr):
    """Write a launch's full stderr to its own log; return what the event keeps."""
    logs = output / "dyld-logs"
    logs.mkdir(exist_ok=True)
    name = (
        key.replace("/", "_").replace(":", "_")
        + f"-{trial:03d}"
        + ("-retry" if retry else "")
    )
    (logs / (name + ".log")).write_text(stderr)
    return {
        "dyld_log": f"dyld-logs/{name}.log",
        "stderr_nondyld": [
            line for line in stderr.splitlines() if not line.startswith("dyld[")
        ],
        "dyld_pid_lines": {pid: len(v) for pid, v in dyld_processes(stderr).items()},
    }


def classify(path):
    if "/pkgs/" in path:
        return "cache"
    if "/envs/" in path:
        return "env"
    return "other"


def cache_index(root):
    """(device, inode) -> cache path for every regular file in the package cache."""
    index = {}
    for path in (root / "pkgs").rglob("*"):
        if path.is_file() and not path.is_symlink():
            info = path.stat()
            index.setdefault((info.st_dev, info.st_ino), str(path))
    return index


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micromamba", type=Path, required=True)
    parser.add_argument("--root-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--natural-trials", type=int, default=20, help="per cell")
    parser.add_argument("--triggered-trials", type=int, default=40, help="per cell")
    parser.add_argument(
        "--delays", default="0,1,2", help="seconds, natural and triggered"
    )
    parser.add_argument("--max-libraries", type=int, default=3)
    parser.add_argument("--phases", default="natural,triggered")
    parser.add_argument(
        "--natural-cells",
        default="hardlink,copy-app,copy-app-print",
        help="comma-separated modes; hardlink expands to one cell per delay",
    )
    args = parser.parse_args()
    if (
        platform.system() != "Darwin"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error("Run only on this experiment's authorized GitHub macOS runner")
    if args.natural_trials < 1 or args.triggered_trials < 1:
        parser.error("Use positive trials")
    args.phases = args.phases.split(",")
    args.natural_cells = args.natural_cells.split(",")
    if not set(args.phases) <= {"natural", "triggered"}:
        parser.error("Unknown phase")
    if not set(args.natural_cells) <= {"hardlink", "copy-app", "copy-app-print"}:
        parser.error("Unknown natural cell")
    return args


def build(name, output):
    source = Path(__file__).with_name(name + ".c")
    shutil.copy2(source, output / source.name)
    binary = output / name
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
    return binary


def main():  # noqa: C901
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = args.root_prefix.resolve()
    command = [str(args.micromamba), "-r", str(root)]
    lock = Path(__file__).resolve().parent / "fixtures/conda-osx-arm64.lock"
    env_clean = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    env_print = {**env_clean, "DYLD_PRINT_LIBRARIES": "1"}
    delays = [float(d) for d in args.delays.split(",")]
    metadata = {
        "platform": platform.platform(),
        "natural_trials": args.natural_trials,
        "triggered_trials": args.triggered_trials,
        "delays": delays,
        "max_libraries": args.max_libraries,
        "phases": args.phases,
        "natural_cells": args.natural_cells,
        "micromamba": subprocess.check_output(
            [*command, "--version"], text=True
        ).strip(),
        "root_prefix": str(root),
        "seed": 982,
        "original_error_uuid": ORIGINAL_UUID,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    counts = {
        "natural": collections.defaultdict(collections.Counter),
        "triggered": collections.defaultdict(collections.Counter),
        "census": collections.Counter(),
    }

    def save_counts():
        (output / "summary.json").write_text(json.dumps(counts, indent=2) + "\n")

    with (output / "events.jsonl").open("w", buffering=1) as events:

        def record(event):
            events.write(json.dumps(event) + "\n")

        def run_logged(arguments, label):
            started = time.time_ns()
            with (output / (label + ".log")).open("w") as log:
                proc = subprocess.Popen(
                    [*command, *arguments],
                    env=env_clean,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                rc = proc.wait(timeout=300)
            record(
                {
                    "event": "command",
                    "label": label,
                    "command": arguments,
                    "pid": proc.pid,
                    "started_ns": started,
                    "ended_ns": time.time_ns(),
                    "returncode": rc,
                }
            )
            if rc:
                raise RuntimeError(f"{label} failed; inspect log")

        def files(name):
            # Pure path construction: no filesystem access before a measured launch.
            prefix = root / "envs" / name
            return {
                "cache_app": cache_app,
                "env_app": prefix / "bin/gdalinfo",
                "prefix": prefix,
            }

        # ---- census on a dedicated environment ------------------------------
        name = "gdal-census"
        run_logged(["create", "-y", "-n", name, "-f", str(lock)], "census-create")
        # Resolve the cached executable once, here, so no trial searches for it.
        cached = list((root / "pkgs").glob("**/libgdal-3.6.2-h51eea9d_5/bin/gdalinfo"))
        if len(cached) != 1:
            raise RuntimeError(f"Expected one cached gdalinfo, found {cached}")
        cache_app = cached[0]
        index = cache_index(root)
        prefix = root / "envs" / name
        rows = []
        for path in sorted(
            p for p in prefix.rglob("*") if p.is_file() and not p.is_symlink()
        ):
            if not is_macho(path):
                continue
            info = path.stat()
            rows.append(
                {
                    "path": str(path.relative_to(prefix)),
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "nlink": info.st_nlink,
                    "size": info.st_size,
                    "cache_alias": index.get((info.st_dev, info.st_ino)),
                }
            )
        (output / "census.json").write_text(json.dumps(rows, indent=1) + "\n")
        c = counts["census"]
        for row in rows:
            dylib = row["path"].endswith((".dylib", ".so"))
            linked = row["cache_alias"] is not None
            c["macho_files"] += 1
            c["macho_cache_linked"] += linked
            c["macho_multilink_not_cache"] += row["nlink"] > 1 and not linked
            c["macho_bytes"] += row["size"]
            c["macho_cache_linked_bytes"] += row["size"] if linked else 0
            if dylib:
                c["dylib_files"] += 1
                c["dylib_cache_linked"] += linked
                c["dylib_bytes"] += row["size"]
                c["dylib_cache_linked_bytes"] += row["size"] if linked else 0
        save_counts()
        run_logged(["env", "remove", "-y", "-n", name], "census-remove")

        def natural_launch(name, key, trial, print_libraries, retry=False):
            started = time.time_ns()
            # `micromamba run` goes through /bin/bash, a SIP-restricted binary that
            # drops DYLD_ variables from its environment, so the printing cell sets
            # the variable inside the command instead of inheriting it.
            launch = (
                ["/usr/bin/env", "DYLD_PRINT_LIBRARIES=1", "gdalinfo", "--version"]
                if print_libraries
                else ["gdalinfo", "--version"]
            )
            proc = subprocess.Popen(
                [*command, "run", "-n", name, *launch],
                env=env_clean,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(timeout=60)
            signature = (
                SIGNATURE in stderr and ORIGINAL_UUID in stderr and "/pkgs/" in stderr
            )
            images = gdal_images(stderr) if print_libraries else None
            result = {
                "event": "natural_launch",
                "case": key,
                "trial": trial,
                "name": name,
                "retry": retry,
                "pid": proc.pid,
                "started_ns": started,
                "ended_ns": time.time_ns(),
                "returncode": proc.returncode,
                "stdout": stdout,
                "original_signature": signature,
                "images": images,
                **(
                    archive_stderr(output, key, trial, retry, stderr)
                    if print_libraries
                    else {"stderr": stderr}
                ),
            }
            record(result)
            if not retry:
                cell = counts["natural"][key]
                cell["launches"] += 1
                cell["failures"] += proc.returncode != 0
                cell["original_signature"] += signature
                if print_libraries:
                    cell["gdal_images_found"] += images is not None
                    if images:
                        cache_images = [p for p in images if classify(p) == "cache"]
                        cell["images"] += len(images)
                        cell["cache_images"] += len(cache_images)
                        cell["launches_with_cache_image"] += bool(cache_images)
                        cell["main_image_cache"] += classify(images[0]) == "cache"
                save_counts()
            if proc.returncode:
                print("FAIL", key, trial, stderr.strip()[-400:], flush=True)
            return result

        # ---- natural phase -------------------------------------------------
        cells = [("hardlink", d) for d in delays if "hardlink" in args.natural_cells]
        cells += [
            (m, 0.0) for m in ("copy-app", "copy-app-print") if m in args.natural_cells
        ]
        if "natural" not in args.phases:
            cells = []
        cases = [
            (mode, delay, t)
            for mode, delay in cells
            for t in range(args.natural_trials)
        ]
        random.Random(982).shuffle(cases)
        for index_, (mode, delay, trial) in enumerate(cases):
            name = f"gdal-nat-{index_:03d}"
            key = f"{mode}/delay{delay:g}s"
            print("CREATE", index_, key, flush=True)
            run_logged(
                ["create", "-y", "-n", name, "-f", str(lock)], f"{index_:03d}-create"
            )
            created_ns = time.time_ns()
            paths = files(name)
            if mode.startswith("copy-app"):
                # The only operations on either alias before the launch: the
                # byte copy itself reads the cache alias and creates the
                # environment alias from this live thread.
                paths["env_app"].unlink()
                shutil.copy2(paths["cache_app"], paths["env_app"])
            if delay:
                time.sleep(delay)
            launched_ns = time.time_ns()
            printing = mode == "copy-app-print"
            result = natural_launch(name, key, trial, print_libraries=printing)
            if result["returncode"]:
                natural_launch(name, key, trial, print_libraries=printing, retry=True)
            after = {k: fingerprint(paths[k]) for k in ("cache_app", "env_app")}
            if mode.startswith("copy-app"):
                assert after["env_app"]["nlink"] == 1, after
                assert after["env_app"]["inode"] != after["cache_app"]["inode"], after
            else:
                assert after["env_app"]["inode"] == after["cache_app"]["inode"], after
            assert after["env_app"]["sha256"] == after["cache_app"]["sha256"], after
            record(
                {
                    "event": "natural_trial",
                    "index": index_,
                    "case": key,
                    "trial": trial,
                    "created_ns": created_ns,
                    "launched_ns": launched_ns,
                    "files_after": after,
                }
            )
            run_logged(["env", "remove", "-y", "-n", name], f"{index_:03d}-remove")
            print("DONE", index_, json.dumps(counts["natural"][key]), flush=True)

        # ---- triggered phase -----------------------------------------------
        if "triggered" not in args.phases:
            print(json.dumps(counts, indent=2), flush=True)
            return
        touch_exit = build("touch_exit", output)
        prime_exec = build("prime_exec", output)
        name = "gdal-trig"
        run_logged(["create", "-y", "-n", name, "-f", str(lock)], "trig-create")
        paths = files(name)
        template_app = output / "template-app"
        shutil.copy2(paths["cache_app"], template_app)
        index = cache_index(root)

        # Which libraries does gdalinfo load, and which of them are cache hardlinks?
        images = None
        for attempt in range(5):
            probe = subprocess.run(
                [str(paths["env_app"]), "--version"],
                env=env_print,
                capture_output=True,
                text=True,
                timeout=60,
            )
            images = gdal_images(probe.stderr)
            # A failure here is itself a natural first-launch failure; it is
            # recorded and the launch retried rather than ending the job.
            record(
                {
                    "event": "listing_launch",
                    "attempt": attempt,
                    "returncode": probe.returncode,
                    "original_signature": SIGNATURE in probe.stderr
                    and "/pkgs/" in probe.stderr,
                    "main_image": images[0] if images else None,
                    **archive_stderr(output, "listing", attempt, False, probe.stderr),
                }
            )
            if probe.returncode == 0 and images:
                break
        else:
            raise RuntimeError(
                f"library listing launch failed five times: {probe.stderr[-400:]}"
            )
        loaded = []
        for image in images[1:]:
            p = Path(image)
            if not p.exists():
                continue
            info = p.stat()
            loaded.append(
                {
                    "path": image,
                    "class": classify(image),
                    "nlink": info.st_nlink,
                    "inode": info.st_ino,
                    "cache_alias": index.get((info.st_dev, info.st_ino)),
                }
            )
        (output / "loaded_libraries.json").write_text(
            json.dumps(loaded, indent=1) + "\n"
        )
        candidates = sorted(
            (row for row in loaded if row["class"] == "env" and row["cache_alias"]),
            key=lambda r: r["path"],
        )[: args.max_libraries]
        libraries = {}
        for row in candidates:
            lib_name = Path(row["path"]).name
            template = output / f"template-{lib_name}"
            shutil.copy2(row["cache_alias"], template)
            libraries[lib_name] = {
                "env": Path(row["path"]),
                "cache": Path(row["cache_alias"]),
                "template": template,
            }
        record(
            {
                "event": "triggered_setup",
                "images": images,
                "loaded": loaded,
                "libraries": {
                    k: {kk: str(vv) for kk, vv in v.items()}
                    for k, v in libraries.items()
                },
            }
        )
        counts["census"]["loaded_libraries"] = len(loaded)
        counts["census"]["loaded_libraries_cache_linked"] = sum(
            1 for row in loaded if row["class"] == "env" and row["cache_alias"]
        )
        save_counts()

        def fresh(mode, cache, env_path, template):
            """Give the cache alias a fresh inode and link or copy it into the environment."""
            env_path.unlink()
            cache.unlink()
            shutil.copy2(template, cache)
            (os.link if mode == "hardlink" else shutil.copy2)(cache, env_path)
            c, e = cache.stat(), env_path.stat()
            assert (c.st_ino == e.st_ino) == (mode == "hardlink"), (
                mode,
                c.st_ino,
                e.st_ino,
            )

        cells = [("hardlink-app", "trigger-app", None, d) for d in delays]
        cells += [
            ("hardlink-app", "none", None, 0.0),
            ("copy-app", "trigger-app", None, 0.0),
        ]
        for lib_name in libraries:
            cells += [
                ("copy-app", "trigger-lib", lib_name, 0.0),
                ("copy-app", "none-lib", lib_name, 0.0),
            ]
        cases = [
            (app, trigger, lib_name, delay, t)
            for app, trigger, lib_name, delay in cells
            for t in range(args.triggered_trials)
        ]
        random.Random(983).shuffle(cases)
        for app, trigger, lib_name, delay, trial in cases:
            key = (
                f"{app}/{trigger}"
                + (f":{lib_name}" if lib_name else "")
                + f"/delay{delay:g}s"
            )
            fresh(
                "hardlink" if app == "hardlink-app" else "copy",
                paths["cache_app"],
                paths["env_app"],
                template_app,
            )
            lib = libraries[lib_name] if lib_name else None
            if lib:
                fresh("hardlink", lib["cache"], lib["env"], lib["template"])
            if trigger == "trigger-app":
                subprocess.run(
                    [str(touch_exit), str(paths["cache_app"]), "0"],
                    env=env_clean,
                    check=True,
                    timeout=10,
                )
            elif trigger == "trigger-lib":
                subprocess.run(
                    [str(touch_exit), str(lib["cache"]), "0"],
                    env=env_clean,
                    check=True,
                    timeout=10,
                )
            if delay:
                time.sleep(delay)
            started = time.time_ns()
            proc = subprocess.run(
                [
                    str(prime_exec),
                    "env-dead",
                    str(paths["cache_app"]),
                    str(paths["env_app"]),
                    "spawn",
                    "0",
                ],
                env=env_print if lib else env_clean,
                capture_output=True,
                text=True,
                timeout=60,
            )
            signature = (
                SIGNATURE in proc.stderr
                and ORIGINAL_UUID in proc.stderr
                and "/pkgs/" in proc.stderr
            )
            images = gdal_images(proc.stderr) if lib else None
            lib_class = None
            if lib:
                if images:
                    matches = [p for p in images if Path(p).name == lib_name]
                    lib_class = classify(matches[0]) if matches else "missing"
                else:
                    lib_class = "unparsed"
            cell = counts["triggered"][key]
            cell["launches"] += 1
            cell["failures"] += proc.returncode != 0
            cell["original_signature"] += signature
            if lib:
                cell["gdal_images_found"] += images is not None
                cell["target_lib_cache"] += lib_class == "cache"
                cell["target_lib_env"] += lib_class == "env"
                cell["target_lib_missing"] += lib_class == "missing"
                cell["target_lib_unparsed"] += lib_class == "unparsed"
                if images:
                    cell["cache_images"] += sum(classify(p) == "cache" for p in images)
                    cell["main_image_cache"] += classify(images[0]) == "cache"
            save_counts()
            record(
                {
                    "event": "triggered_launch",
                    "case": key,
                    "trial": trial,
                    "started_ns": started,
                    "ended_ns": time.time_ns(),
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "original_signature": signature,
                    "images": images,
                    **(
                        archive_stderr(output, key, trial, False, proc.stderr)
                        if lib
                        else {"stderr": proc.stderr}
                    ),
                    "target_lib_class": lib_class,
                    "app": fingerprint(paths["env_app"]),
                    "lib": fingerprint(lib["env"]) if lib else None,
                }
            )
            if proc.returncode:
                print("FAIL", key, trial, proc.stderr.strip()[-400:], flush=True)
        run_logged(["env", "remove", "-y", "-n", name], "trig-remove")
    print(json.dumps(counts, indent=2), flush=True)


if __name__ == "__main__":
    main()
