"""Plot pytest worker occupancy and runner CPU from one measured trial."""

import argparse
import json

from collections import defaultdict
from pathlib import Path

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt

from matplotlib.patches import Patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    tests = defaultdict(list)
    for path in args.artifact.glob("mapping-gw*.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["event"] == "test-report":
                tests[(row["worker"], row["nodeid"])].append(row)
    first = min(r["start"] for rows in tests.values() for r in rows)
    last = max(r["stop"] for rows in tests.values() for r in rows)
    workers = sorted({w for w, _ in tests})
    finish = {
        w: max(
            r["stop"]
            for (worker, _), rows in tests.items()
            for r in rows
            if worker == w
        )
        - first
        for w in workers
    }
    tail_start = sorted(finish.values())[-2]
    plt.rcParams.update({"svg.fonttype": "none", "font.size": 10})
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
    for (worker, nodeid), rows in tests.items():
        begin, end = min(r["start"] for r in rows), max(r["stop"] for r in rows)
        ibis = nodeid.endswith("::test_lock_poetry_ibis")
        axes[0].barh(
            workers.index(worker),
            end - begin,
            left=begin - first,
            height=0.55,
            color="#c56a13" if ibis else "#4576a3",
        )
    axes[0].set(yticks=range(len(workers)), yticklabels=workers, ylabel="pytest worker")
    for worker, end in finish.items():
        axes[0].text(
            end + 1, workers.index(worker), f"{end:.0f}s", va="center", fontsize=9
        )
    axes[0].legend(
        handles=[
            Patch(color="#c56a13", label="Ibis test"),
            Patch(color="#4576a3", label="Other tests"),
        ],
        loc="upper right",
    )
    samples = [
        json.loads(line)
        for line in (args.artifact / "samples.jsonl").read_text().splitlines()
    ]
    samples = [s for s in samples if first <= s["time"] <= last]
    cores = json.loads((args.artifact / "metadata.json").read_text())["logical_cpus"]
    times = [s["time"] - first for s in samples]
    axes[1].plot(
        times, [s["cpu_percent"] for s in samples], label="Runner CPU", color="#4576a3"
    )
    axes[1].plot(
        times,
        [
            s["process_cpu_seconds"].get("mamba.exe", 0)
            / s["interval_seconds"]
            / cores
            * 100
            for s in samples
        ],
        label="Observed Mamba CPU",
        color="#c56a13",
        linewidth=1.2,
    )
    axes[1].axhline(
        25,
        color="#888888",
        linewidth=0.8,
        linestyle=":",
        label="One of four logical CPUs",
    )
    axes[1].set(
        ylabel="All-vCPU utilization (%)",
        xlabel="Seconds since first test started",
        ylim=(0, 105),
    )
    axes[1].legend(loc="upper right", fontsize=9)
    for axis in axes:
        axis.axvspan(tail_start, last - first, color="#dedede", alpha=0.35, zorder=-1)
        axis.axvline(tail_start, color="#666666", linestyle="--", linewidth=0.8)
        axis.set_xlim(0, last - first + 9)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "Windows straggler: three workers finish while one continues", fontsize=14
    )
    fig.supxlabel(
        "Shaded region: only one pytest worker remains. A running test cannot be split across workers.",
        fontsize=9,
    )
    fig.savefig(args.output.with_suffix(".svg"))
    fig.savefig(args.output.with_suffix(".png"), dpi=170)


if __name__ == "__main__":
    main()
