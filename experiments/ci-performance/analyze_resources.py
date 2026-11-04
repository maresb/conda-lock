"""Summarize downloaded one-second measurements by workflow phase."""

import argparse
import csv
import json

from collections import defaultdict
from datetime import datetime
from pathlib import Path


def counter_delta(current, previous, field):
    if field not in current or field not in previous:
        return 0
    return max(0, current[field] - previous[field])


def workflow_steps(directory, metadata):
    context = metadata["context"]
    snapshot = directory.parents[1] / f"run-{context.get('GITHUB_RUN_ID')}.json"
    if not snapshot.exists():
        return []
    matrix = json.loads(context.get("METRICS_MATRIX") or "{}") or {}
    job = context.get("GITHUB_JOB")
    suffix = {
        "test": f"pytest py{matrix.get('python-version')} on {matrix.get('os')} ({matrix.get('pytest-split-group-index')}/{matrix.get('pytest-split-group-size')})",
        "serial": f"serial control ({matrix.get('repeat')})",
        "parallel": f"parallel ({matrix.get('repeat')}, {matrix.get('format')})",
        "local-concurrency": f"Three formats on one runner ({matrix.get('repeat')})",
        "link-threads": f"Link threads ({matrix.get('execute-threads')}, {matrix.get('repeat')})",
        "worker-control": f"Worker control ({matrix.get('pytest-workers')}, {matrix.get('repeat')})",
        "lock-gdal": f"lock-gdal ({matrix.get('os')}, {matrix.get('python-version')})",
    }.get(job)
    if suffix is None:
        return []
    jobs = json.loads(snapshot.read_text())["jobs"]
    matches = [job for job in jobs if job["name"].endswith(suffix)]
    assert len(matches) == 1, (snapshot, suffix)
    return matches[0]["steps"]


def summarize(directory):
    metadata = json.loads((directory / "metadata.json").read_text())
    steps = workflow_steps(directory, metadata)
    samples = [
        json.loads(line)
        for line in (directory / "samples.jsonl").read_text().splitlines()
    ]
    grouped = defaultdict(list)
    previous = None
    for row in samples:
        row["disk_delta"] = {}
        row["network_delta"] = {}
        if previous:
            for category, fields in [
                ("disk", ["read_bytes", "write_bytes", "read_count", "write_count"]),
                ("network", ["bytes_recv", "bytes_sent"]),
            ]:
                current_total = row.get(category + "_total", {})
                previous_total = previous.get(category + "_total", {})
                for field in fields:
                    row[category + "_delta"][field] = counter_delta(
                        current_total, previous_total, field
                    )
        previous = row
        matches = [
            step
            for step in steps
            if step["name"] == row["phase"]
            or step["name"].startswith("Run " + row["phase"] + "@")
        ]
        if matches and matches[0].get("completed_at"):
            step = matches[0]
            begin = datetime.fromisoformat(step["started_at"]).timestamp()
            end = datetime.fromisoformat(step["completed_at"]).timestamp()
            interval = row["interval_seconds"]
            overlap = max(0, min(row["time"], end) - max(row["time"] - interval, begin))
            if overlap == 0:
                continue
            row["interval_seconds"] = overlap
            for key in ["disk_delta", "network_delta", "process_cpu_seconds"]:
                row[key] = {
                    name: value * overlap / interval for name, value in row[key].items()
                }
            row["clipped_to_step"] = True
        grouped[row["phase"]].append(row)
    results = []
    context = metadata["context"]
    matrix = json.loads(context.get("METRICS_MATRIX") or "{}") or {}
    for phase, rows in grouped.items():
        wall = sum(row["interval_seconds"] for row in rows)

        def weighted(key):
            return sum(row[key] * row["interval_seconds"] for row in rows) / wall

        process_seconds = defaultdict(float)
        for row in rows:
            for name, seconds in row["process_cpu_seconds"].items():
                process_seconds[name] += seconds
        cpu = weighted("cpu_percent")
        disk = {
            key: sum(row["disk_delta"].get(key, 0) for row in rows)
            for key in ["read_bytes", "write_bytes", "read_count", "write_count"]
        }
        network = {
            key: sum(row["network_delta"].get(key, 0) for row in rows)
            for key in ["bytes_recv", "bytes_sent"]
        }
        results.append(
            {
                "artifact": directory.name,
                "run": context.get("GITHUB_RUN_ID"),
                "job": context.get("GITHUB_JOB"),
                "os": context.get("RUNNER_OS"),
                "python": matrix.get("python-version"),
                "shards": matrix.get("pytest-split-group-size"),
                "group": matrix.get("pytest-split-group-index"),
                "workers": matrix.get("pytest-workers", "auto"),
                "execute_threads": matrix.get("execute-threads"),
                "format": matrix.get("format"),
                "repeat": matrix.get("repeat"),
                "logical_cpus": metadata["logical_cpus"],
                "physical_cpus": metadata["physical_cpus"],
                "phase": phase,
                "samples": len(rows),
                "clipped_to_workflow_step": any(
                    row.get("clipped_to_step") for row in rows
                ),
                "wall_seconds": wall,
                "cpu_percent": cpu,
                "busy_vcpus": cpu / 100 * metadata["logical_cpus"],
                "busy_cpu_seconds": cpu / 100 * metadata["logical_cpus"] * wall,
                "cpu_p95": sorted(row["cpu_percent"] for row in rows)[
                    int((len(rows) - 1) * 0.95)
                ],
                "fraction_above_80_percent": sum(
                    row["interval_seconds"] for row in rows if row["cpu_percent"] >= 80
                )
                / wall,
                "per_cpu_mean": [
                    sum(
                        row["per_cpu_percent"][index] * row["interval_seconds"]
                        for row in rows
                    )
                    / wall
                    for index in range(metadata["logical_cpus"])
                ],
                "cpu_modes": {
                    key: sum(
                        row["cpu_times_percent"].get(key, 0) * row["interval_seconds"]
                        for row in rows
                    )
                    / wall
                    for key in rows[0]["cpu_times_percent"]
                },
                "disk": disk,
                "network": network,
                "top_process_cpu_seconds": dict(
                    sorted(
                        process_seconds.items(), key=lambda item: item[1], reverse=True
                    )[:8]
                ),
                "monitor_cpu_seconds": metadata.get("monitor_cpu_seconds"),
                "monitor_span_seconds": metadata.get("finished", metadata["started"])
                - metadata["started"],
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    rows = []
    for metadata in sorted(args.root.rglob("metadata.json")):
        rows.extend(summarize(metadata.parent))
    (args.root / "resource-summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    fields = [
        "run",
        "artifact",
        "job",
        "os",
        "python",
        "shards",
        "group",
        "format",
        "repeat",
        "logical_cpus",
        "phase",
        "wall_seconds",
        "cpu_percent",
        "busy_vcpus",
        "busy_cpu_seconds",
        "cpu_p95",
        "fraction_above_80_percent",
    ]
    with (args.root / "resource-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        if row["phase"] in [
            "run-test",
            "Install GDAL with conda-lock",
            "cpu-calibration",
            "idle-calibration",
        ]:
            print(json.dumps({key: row[key] for key in fields if key != "artifact"}))


if __name__ == "__main__":
    main()
