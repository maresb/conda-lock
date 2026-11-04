"""Summarize instrumented mapping-cache trials from downloaded artifacts."""

import argparse
import json

from collections import defaultdict
from datetime import datetime
from pathlib import Path


def elapsed(step):
    return (
        datetime.fromisoformat(step["completed_at"])
        - datetime.fromisoformat(step["started_at"])
    ).total_seconds()


def trace_spans(directory):
    spans = []
    reports = defaultdict(float)
    workers = defaultdict(list)
    for path in directory.glob("mapping-*.jsonl"):
        pending = {}
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["event"] == "test-report" and row["worker"] != "controller":
                reports[row["nodeid"]] += row["duration"]
                workers[row["worker"]].append(row)
            if row["event"] != "cache":
                continue
            message = row["message"]
            kind = None
            if message.startswith("Attempting to acquire lock"):
                pending.setdefault((row["thread"], "lock"), row)
            elif message.startswith("Successfully acquired lock"):
                kind = "lock"
            elif message.startswith("Requesting "):
                pending[(row["thread"], "http")] = row
            elif message.startswith("Downloaded "):
                kind = "http"
            elif message == "Parsing PyPI mapping":
                pending[(row["thread"], "parse")] = row
            elif message.startswith("Loaded "):
                kind = "parse"
            start = pending.pop((row["thread"], kind), None) if kind else None
            if start:
                spans.append(
                    {
                        "kind": kind,
                        "worker": row["worker"],
                        "pid": row["pid"],
                        "test": start["test"],
                        "start": start["time"],
                        "stop": row["time"],
                        "seconds": row["monotonic"] - start["monotonic"],
                        "trace": path.name,
                    }
                )
        if pending:
            raise ValueError(f"Unfinished cache operations in {path}: {pending}")
    first = min(r["start"] for rows in workers.values() for r in rows)
    schedule = {
        name: {
            "test_ids": len({r["nodeid"] for r in rows}),
            "first_test_seconds": min(r["start"] for r in rows) - first,
            "last_test_seconds": max(r["stop"] for r in rows) - first,
            "occupied_seconds": sum(r["duration"] for r in rows),
        }
        for name, rows in workers.items()
    }
    return spans, reports, schedule


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("run_id")
    args = parser.parse_args()
    snapshot = json.loads((args.root / f"run-{args.run_id}.json").read_text())
    resources = json.loads((args.root / "resource-summary.json").read_text())
    trials = []
    for path in sorted((args.root / args.run_id).glob("metrics-*/metadata.json")):
        metadata = json.loads(path.read_text())
        kind = metadata["context"]["GITHUB_JOB"]
        if kind not in ["mapping-control", "scheduling-control"]:
            continue
        matrix = json.loads(metadata["context"]["METRICS_MATRIX"])
        state, workers, repeat = (
            matrix["mapping-cache"],
            matrix["pytest-workers"],
            matrix["repeat"],
        )
        distribution = matrix.get("distribution", "load")
        suffix = (
            f"Mapping control ({state}, {workers}, {repeat})"
            if kind == "mapping-control"
            else f"Scheduling control ({distribution}, {repeat})"
        )
        job = next(j for j in snapshot["jobs"] if j["name"].endswith(suffix))
        steps = {s["name"]: s for s in job["steps"]}
        spans, reports, schedule = trace_spans(path.parent)
        cpu = next(
            r
            for r in resources
            if r["artifact"] == path.parent.name and r["phase"] == "run-test"
        )
        prepare = elapsed(steps["Prepare mapping cache"])
        test = elapsed(steps["run-test"])
        trials.append(
            {
                "job_id": job["id"],
                "conclusion": job["conclusion"],
                "artifact": path.parent.name,
                "cache": state,
                "workers": int(workers),
                "repeat": repeat,
                "distribution": distribution,
                "prepare_seconds": prepare,
                "pytest_seconds": test,
                "combined_seconds": prepare + test,
                "cpu_percent": cpu["cpu_percent"],
                "test_ids": len(reports),
                "http_seconds": sum(s["seconds"] for s in spans if s["kind"] == "http"),
                "max_worker_lock_wait_seconds": max(
                    (
                        s["seconds"]
                        for s in spans
                        if s["kind"] == "lock" and s["worker"] != "controller"
                    ),
                    default=0,
                ),
                "spans": spans,
                "worker_schedule": schedule,
                "single_worker_tail_seconds": sorted(
                    w["last_test_seconds"] for w in schedule.values()
                )[-1]
                - sorted(w["last_test_seconds"] for w in schedule.values())[-2],
                "slowest_tests": sorted(
                    reports.items(), key=lambda item: item[1], reverse=True
                )[:10],
            }
        )
    trials.sort(
        key=lambda t: (t["cache"], t["workers"], t["distribution"], t["repeat"])
    )
    groups = defaultdict(list)
    for trial in trials:
        groups[(trial["cache"], trial["workers"], trial["distribution"])].append(trial)
    summaries = [
        {
            "cache": state,
            "workers": workers,
            "distribution": distribution,
            "repetitions": len(values),
            **{
                name: sum(v[name] for v in values) / len(values)
                for name in [
                    "prepare_seconds",
                    "pytest_seconds",
                    "combined_seconds",
                    "http_seconds",
                ]
            },
        }
        for (state, workers, distribution), values in sorted(groups.items())
    ]
    result = {
        "run_id": args.run_id,
        "trials": trials,
        "summaries": summaries,
        "timing_note": "HTTP spans run from the Requesting log to Downloaded (including response handling and cache write). Lock spans include all timeout/retry cycles until acquisition.",
    }
    (args.root / f"mapping-results-{args.run_id}.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    for trial in trials:
        print(
            json.dumps(
                {
                    k: v
                    for k, v in trial.items()
                    if k not in ["spans", "slowest_tests", "worker_schedule"]
                }
            )
        )
    for summary in summaries:
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
