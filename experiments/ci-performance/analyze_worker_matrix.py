"""Compare complete Windows matrices and verify identical shard test IDs."""

import argparse
import hashlib
import json

from collections import defaultdict
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    resources = json.loads((args.root / "resource-summary.json").read_text())
    trials = []
    reference = {}
    unions = defaultdict(set)
    counts = defaultdict(int)
    for run in args.runs:
        jobs = json.loads((args.root / f"run-{run}.json").read_text())["jobs"]
        for path in sorted((args.root / run).glob("metrics-*/metadata.json")):
            meta = json.loads(path.read_text())
            if meta["context"]["GITHUB_JOB"] != "worker-matrix":
                continue
            m = json.loads(meta["context"]["METRICS_MATRIX"])
            py, group, workers = (
                m["python-version"],
                m["pytest-split-group-index"],
                int(m["pytest-workers"]),
            )
            distribution = m.get("distribution", "load")
            job = next(
                j
                for j in jobs
                if j["name"].endswith(
                    f"Worker matrix (py{py}, group {group}, workers {workers})"
                )
            )
            assert job["conclusion"] == "success", job["name"]
            step = next(s for s in job["steps"] if s["name"] == "run-test")
            seconds = (
                datetime.fromisoformat(step["completed_at"])
                - datetime.fromisoformat(step["started_at"])
            ).total_seconds()
            ids = set(json.loads((path.parent / "test-durations.json").read_text()))
            reference.setdefault((py, group), ids)
            assert ids == reference[(py, group)], (run, m)
            cohort = (run, py, workers, distribution)
            unions[cohort].update(ids)
            counts[cohort] += len(ids)
            cpu = next(
                r
                for r in resources
                if r["artifact"] == path.parent.name and r["phase"] == "run-test"
            )
            trials.append(
                {
                    "run_id": run,
                    "job_id": job["id"],
                    "artifact": path.parent.name,
                    "python": py,
                    "group": group,
                    "workers": workers,
                    "distribution": distribution,
                    "step_seconds": seconds,
                    "cpu_percent": cpu["cpu_percent"],
                    "sampled_seconds": cpu["wall_seconds"],
                    "busy_cpu_seconds": cpu["busy_cpu_seconds"],
                    "test_ids": len(ids),
                    "test_ids_sha256": hashlib.sha256(
                        "\n".join(sorted(ids)).encode()
                    ).hexdigest(),
                }
            )
    for cohort, ids in unions.items():
        assert len(ids) == counts[cohort] == 344, (cohort, len(ids), counts[cohort])
        baseline = set(
            json.loads(
                (
                    args.root
                    / "41889214378"
                    / "aggregated-test-durations"
                    / f"windows-latest-py{cohort[1]}.json"
                ).read_text()
            )
        )
        assert ids == baseline, cohort
    grouped = defaultdict(list)
    for trial in trials:
        grouped[(trial["run_id"], trial["workers"], trial["distribution"])].append(
            trial
        )
    summaries = []
    for (run, workers, distribution), values in sorted(grouped.items()):
        assert len(values) == 8, (run, workers, distribution)
        wall = sum(r["sampled_seconds"] for r in values)
        cpu = sum(r["busy_cpu_seconds"] for r in values)
        summaries.append(
            {
                "run_id": run,
                "workers": workers,
                "distribution": distribution,
                "jobs": len(values),
                "step_seconds_sum": sum(r["step_seconds"] for r in values),
                "step_seconds_max": max(r["step_seconds"] for r in values),
                "cpu_percent": cpu / wall / 4 * 100,
                "busy_cpu_seconds": cpu,
                "test_ids_per_python": 344,
            }
        )
    result = {
        "summaries": summaries,
        "trials": sorted(
            trials, key=lambda r: (r["run_id"], r["workers"], r["python"], r["group"])
        ),
    }
    (args.root / "worker-matrix-results.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    for summary in summaries:
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
