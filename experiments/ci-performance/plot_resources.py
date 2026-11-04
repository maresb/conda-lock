"""Plot an individual downloaded runner trace (requires matplotlib)."""

import argparse
import json

from itertools import pairwise
from pathlib import Path

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    metadata = json.loads((args.directory / "metadata.json").read_text())
    samples = [
        json.loads(line)
        for line in (args.directory / "samples.jsonl").read_text().splitlines()
    ]
    start = metadata["started"]
    times = [(row["time"] - start) / 60 for row in samples]
    fig, axes = plt.subplots(
        4,
        1,
        figsize=(12, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [2, 1.3, 1.4, 1.4]},
        layout="constrained",
    )
    fig.suptitle(args.title, fontsize=15)
    axes[0].plot(
        times, [row["cpu_percent"] for row in samples], color="#164e8c", linewidth=1.6
    )
    axes[0].set(ylabel="All-vCPU utilization (%)", ylim=(0, 105))
    cores = metadata["logical_cpus"]
    heat = axes[1].imshow(
        [[row["per_cpu_percent"][index] for row in samples] for index in range(cores)],
        extent=[times[0], times[-1], cores - 0.5, -0.5],
        aspect="auto",
        vmin=0,
        vmax=100,
        cmap="Blues",
    )
    axes[1].set(ylabel="Logical vCPU", yticks=list(range(cores)))
    fig.colorbar(heat, ax=axes[1], label="Utilization (%)", pad=0.01)
    for axis, category, fields in [
        (axes[2], "disk_total", ["read_bytes", "write_bytes"]),
        (axes[3], "network_total", ["bytes_recv", "bytes_sent"]),
    ]:
        for field in fields:
            rates = [0]
            for old, new in pairwise(samples):
                delta = new.get(category, {}).get(field, 0) - old.get(category, {}).get(
                    field, 0
                )
                rates.append(max(0, delta) / new["interval_seconds"] / 2**20)
            axis.plot(
                times,
                rates,
                linewidth=1.1,
                label=field.replace("_bytes", "").replace("bytes_", ""),
            )
        axis.legend(loc="upper right", ncol=2, fontsize=8)
        axis.set(
            ylabel=("Disk" if category == "disk_total" else "Network") + " (MiB/s)"
        )
    labels = {
        "conda-incubator/setup-miniconda": "Miniconda setup",
        "mamba-org/setup-micromamba": "Environment restore/setup",
        "install conda-lock": "Install conda-lock",
        "run-test": "Tests / locking",
        "Install GDAL with conda-lock": "GDAL installation + checks",
    }
    phases = [
        json.loads(line)
        for line in (args.directory / "phases.jsonl").read_text().splitlines()
    ]
    for index, phase in enumerate(phases):
        if phase["phase"] not in labels:
            continue
        begin = (phase["time"] - start) / 60
        end = (
            (phases[index + 1]["time"] - start) / 60
            if index + 1 < len(phases)
            else times[-1]
        )
        for axis in [axes[0], axes[2], axes[3]]:
            axis.axvspan(begin, end, color="#64748b", alpha=0.08)
            axis.axvline(begin, color="#64748b", alpha=0.35, linewidth=0.7)
        axes[0].text(
            (begin + end) / 2,
            102,
            labels[phase["phase"]],
            ha="center",
            va="bottom",
            fontsize=8,
        )
    axes[-1].set(xlabel="Minutes since sampling started")
    for axis in [axes[0], axes[2], axes[3]]:
        axis.grid(alpha=0.2)
        axis.set_xlim(0, times[-1])
    fig.savefig(args.directory / "resources.png", dpi=160)
    fig.savefig(args.directory / "resources.svg")


if __name__ == "__main__":
    main()
