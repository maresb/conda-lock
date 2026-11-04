"""One-second, system-wide runner measurements; no command lines or secrets."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import uuid

from pathlib import Path

import psutil


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def counters(function):
    try:
        return {name: value._asdict() for name, value in function().items()}
    except (OSError, psutil.Error) as error:
        return {"error": str(error)}


def total_counters(function):
    try:
        value = function()
        return value._asdict() if value is not None else {}
    except (OSError, psutil.Error) as error:
        return {"error": str(error)}


def processes():
    result = {}
    for process in psutil.process_iter(["pid", "name", "create_time", "cpu_times"]):
        try:
            info = process.info
            if info["pid"] == 0:
                continue
            cpu = info["cpu_times"]
            if cpu is not None:
                result[str(info["pid"])] = {
                    "name": info["name"],
                    "created": info["create_time"],
                    "cpu_seconds": cpu.user + cpu.system,
                }
        except (OSError, psutil.Error):
            continue
    return result


def mark(root, label):
    temporary = root / f"phase-{uuid.uuid4().hex}.tmp"
    temporary.write_text(label)
    temporary.replace(root / "phase.txt")
    with (root / "phases.jsonl").open("a") as stream:
        stream.write(json.dumps({"time": time.time(), "phase": label}) + "\n")


def sample(root):
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "psutil": psutil.__version__,
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "memory_bytes": psutil.virtual_memory().total,
        "context": {
            key: os.environ.get(key)
            for key in [
                "GITHUB_RUN_ID",
                "GITHUB_SHA",
                "GITHUB_JOB",
                "RUNNER_OS",
                "RUNNER_ARCH",
                "ImageOS",
                "ImageVersion",
                "METRICS_MATRIX",
                "METRICS_INPUTS",
                "METRICS_ID",
            ]
        },
        "started": time.time(),
    }
    write_json(root / "metadata.json", metadata)
    psutil.cpu_percent(percpu=True)
    psutil.cpu_times_percent()
    previous_processes = processes()
    previous_time = time.monotonic()
    previous_wall = time.time()
    (root / "ready").touch()
    with (root / "samples.jsonl").open("w", buffering=1) as stream:
        while not (root / "stop").exists():
            time.sleep(max(0, 1 - (time.monotonic() - previous_time)))
            now = time.monotonic()
            wall = time.time()
            interval = now - previous_time
            per_cpu = psutil.cpu_percent(percpu=True)
            current_processes = processes()
            by_name = {}
            for pid, current in current_processes.items():
                previous = previous_processes.get(pid)
                if previous and previous["created"] == current["created"]:
                    delta = current["cpu_seconds"] - previous["cpu_seconds"]
                elif current["created"] and current["created"] >= previous_wall:
                    delta = current["cpu_seconds"]
                else:
                    continue
                name = current["name"]
                by_name[name] = by_name.get(name, 0) + max(0, delta)
            row = {
                "time": wall,
                "interval_seconds": interval,
                "phase": (root / "phase.txt").read_text(),
                "cpu_percent": sum(per_cpu) / len(per_cpu),
                "per_cpu_percent": per_cpu,
                "cpu_times_percent": psutil.cpu_times_percent()._asdict(),
                "disk": counters(lambda: psutil.disk_io_counters(perdisk=True)),
                "disk_total": total_counters(psutil.disk_io_counters),
                "network": counters(lambda: psutil.net_io_counters(pernic=True)),
                "network_total": total_counters(psutil.net_io_counters),
                "memory_available": psutil.virtual_memory().available,
                "process_cpu_seconds": dict(
                    sorted(by_name.items(), key=lambda item: item[1], reverse=True)[:12]
                ),
            }
            stream.write(json.dumps(row) + "\n")
            previous_time, previous_wall = now, wall
            previous_processes = current_processes
    metadata.update(
        {"finished": time.time(), "monitor_cpu_seconds": time.process_time()}
    )
    write_json(root / "metadata.json", metadata)
    (root / "done").touch()


def start(root):
    root.mkdir(parents=True, exist_ok=False)
    mark(root, "idle-calibration")
    identifier = uuid.uuid4().hex
    os.environ["METRICS_ID"] = identifier
    options = {}
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        options["start_new_session"] = True
    with (root / "monitor.log").open("w") as stream:
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "sample",
                "--directory",
                str(root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            **options,
        )
    (root / "pid").write_text(str(child.pid))
    for _ in range(100):
        if (root / "ready").exists():
            break
        if child.poll() is not None:
            raise RuntimeError((root / "monitor.log").read_text())
        time.sleep(0.1)
    else:
        raise RuntimeError("Sampler did not start")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a") as stream:
            stream.write(f"METRICS_ID={identifier}\n")
    time.sleep(5)


def stop(root):
    (root / "stop").touch()
    for _ in range(100):
        if (root / "done").exists():
            print((root / "metadata.json").read_text())
            return
        time.sleep(0.1)
    raise RuntimeError("Sampler did not stop: " + (root / "monitor.log").read_text())


def burn(seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        sum(value * value for value in range(10000))


def calibrate(root, workers):
    mark(root, "cpu-calibration")
    children = [
        subprocess.Popen([sys.executable, __file__, "burn"]) for _ in range(workers)
    ]
    for child in children:
        assert child.wait() == 0
    mark(root, "idle-after-calibration")
    time.sleep(3)
    stop(root)
    rows = [
        json.loads(line) for line in (root / "samples.jsonl").read_text().splitlines()
    ]
    loaded = [row for row in rows if row["phase"] == "cpu-calibration"]
    average_cores = sum(sum(row["per_cpu_percent"]) / 100 for row in loaded) / len(
        loaded
    )
    print(json.dumps({"load_workers": workers, "measured_busy_cores": average_cores}))
    assert average_cores >= workers * 0.6, (
        "CPU load was not visible in the measurements"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["start", "sample", "mark", "stop", "calibrate", "burn"]
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "ci-metrics",
    )
    parser.add_argument("--label", default="unlabelled")
    parser.add_argument("--workers", type=int, default=min(psutil.cpu_count() or 1, 8))
    args = parser.parse_args()
    if args.action == "burn":
        burn(8)
    elif args.action == "mark":
        mark(args.directory, args.label)
    elif args.action == "calibrate":
        calibrate(args.directory, args.workers)
    else:
        {"start": start, "stop": stop, "sample": sample}[args.action](args.directory)


if __name__ == "__main__":
    main()
