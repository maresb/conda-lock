"""Plot the recorded CPU experiment summaries (requires matplotlib)."""

import json

from pathlib import Path

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    root = Path(__file__).parent
    cases = json.loads((root / "cpu-results.json").read_text())["cases"]
    plt.rcParams.update({"svg.fonttype": "none", "font.size": 10})
    fig, axes = plt.subplots(2, 3, figsize=(11, 6), layout="constrained")
    comparisons = [
        (
            "Linux pytest\n3 shards per Python",
            ["linux_2", "linux_4"],
            ["2 workers", "4 workers"],
            "step_seconds_sum",
            "Sum of 6 test steps (s)",
        ),
        (
            "Windows pytest\n4 shards per Python",
            ["windows_4shards_2", "windows_4shards_4"],
            ["2 workers", "4 workers"],
            "step_seconds_sum",
            "Sum of 8 test steps (s)",
        ),
        (
            "Windows GDAL installation\n3 formats installed serially",
            ["link_threads_1", "link_threads_4"],
            ["1 link thread", "4 link threads"],
            "step_seconds_mean",
            "Mean install/check step (s)",
        ),
    ]
    for column, (title, keys, labels, metric, ylabel) in enumerate(comparisons):
        summaries = [cases[key]["summary"] for key in keys]
        for row, field, axis_label in [
            (0, "cpu_percent", "All-vCPU utilization (%)"),
            (1, metric, ylabel),
        ]:
            axis = axes[row, column]
            values = [s[field] for s in summaries]
            bars = axis.bar(labels, values, color=["#657c99", "#007f7a"], width=0.55)
            axis.bar_label(bars, fmt="%.1f" if row == 0 else "%.0f", padding=4)
            axis.set(
                ylabel=axis_label, ylim=(0, 100 if row == 0 else max(values) * 1.2)
            )
            axis.spines[["top", "right"]].set_visible(False)
            if row == 0:
                axis.set_title(title, pad=12)
    fig.suptitle(
        "Higher CPU utilization helped Linux; Windows elapsed times barely changed",
        fontsize=13,
    )
    fig.supxlabel(
        "Four logical vCPUs / two physical cores per runner. Small trials; see report for repeats and limitations.",
        fontsize=9,
    )
    fig.savefig(root / "cpu-comparison.svg")
    fig.savefig(root / "cpu-comparison.png", dpi=170)


if __name__ == "__main__":
    main()
