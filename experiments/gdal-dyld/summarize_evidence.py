#!/usr/bin/env python3
"""Print the result tables in FOLLOWUP-RESULTS.md from followup-evidence.json.

Every range and total in that document should be pasted from this output.
Run: python3 summarize_evidence.py followup-evidence.json
"""

import json
import sys


TOUCHERS = [
    ("none", "Nothing (control)"),
    ("main", "Its main thread"),
    ("worker1", "One exited worker"),
    ("worker4", "Four exited workers"),
]
LAUNCHES = ["python", "launcher-spawn", "launcher-exec"]
VOLUMES = ["host-apfs", "image-apfs", "image-hfs"]
ROUTE2 = [
    ("none", "None"),
    ("stat-cache", "`stat` of the cache alias"),
    ("open-cache", "`open` and `close` of the cache alias"),
    (
        "open-cache-stat-env",
        "`open` of the cache alias, then `stat` of the environment alias",
    ),
]


def values(runs, job, key, field="cache_path"):
    out = []
    for run in runs:
        summary = run["summaries"].get(job)
        if summary and key in summary:
            out.append(summary[key][field])
    return out


def fmt_range(vals):
    if not vals:
        return "n/a"
    return str(vals[0]) if min(vals) == max(vals) else f"{min(vals)} to {max(vals)}"


def nonzero_elsewhere(runs, job, expected):
    found = []
    for run in runs:
        for key, cell in (run["summaries"].get(job) or {}).items():
            if cell.get("cache_path") and expected not in key:
                found.append((run["id"], key, cell["cache_path"]))
    return found or "none"


def print_runs(runs):
    print("## Runs\n")
    for run in runs:
        failed = [j["name"] for j in run["jobs"] if j["conclusion"] != "success"]
        print(
            f"- {run['id']} `{run['head_sha'][:9]}` {run['conclusion']}; failed jobs: {failed or 'none'}"
        )


def print_cross_process(runs):
    print("\n## Cross-process (cache paths out of 30 per run; range over runs)\n")
    print(
        "| Finished process looked up cache from | Python launches directly | Launcher spawns | Launcher execs |"
    )
    print("|---|---:|---:|---:|")
    for toucher, label in TOUCHERS:
        cells = [
            fmt_range(values(runs, "cross-process", f"hardlink/{toucher}/{launch}"))
            for launch in LAUNCHES
        ]
        print(f"| {label} | " + " | ".join(cells) + " |")
    copies = [
        values(runs, "cross-process", f"copy/{t}/{launch}")
        for t, _ in TOUCHERS
        for launch in LAUNCHES
    ]
    print(
        f"| Any, copied executable | {sum(map(sum, copies))}/{30 * sum(map(len, copies))} total | | |"
    )
    print(
        f"\nRuns with this job: {len(values(runs, 'cross-process', 'hardlink/none/python'))}"
    )


def scrub_rows():
    rows = [
        ("Nothing, `spawn`", "hardlink/stale1/dummies0/holders0/evictors0/spawn"),
        ("Nothing, `exec`", "hardlink/stale1/dummies0/holders0/evictors0/exec"),
    ]
    rows += [
        (
            f"{d} dummy threads created and joined",
            f"hardlink/stale1/dummies{d}/holders0/evictors0/spawn",
        )
        for d in [1, 2, 4, 8]
    ]
    rows += [
        (
            f"{h} holder threads kept alive",
            f"hardlink/stale1/dummies0/holders{h}/evictors0/spawn",
        )
        for h in [1, 2, 4]
    ]
    rows += [
        (
            f"{e} live threads that looked up the environment alias before the worker exited",
            f"hardlink/stale1/dummies0/holders0/evictors{e}/spawn",
        )
        for e in [1, 3, 5, 6, 7, 8, 10]
    ]
    rows += [
        (
            f"{e} live threads created before the worker exited, no lookup",
            f"hardlink/stale1/dummies0/holders0/evictors{e}-none/spawn",
        )
        for e in [7, 10]
    ]
    rows += [
        (
            f"{e} live threads created before the worker exited, lookup of an unrelated file",
            f"hardlink/stale1/dummies0/holders0/evictors{e}-other/spawn",
        )
        for e in [7, 10]
    ]
    rows += [
        ("No cache worker", "hardlink/stale0/dummies0/holders0/evictors0/spawn"),
        ("Copied executable", "copy/stale1/dummies0/holders0/evictors0/spawn"),
    ]
    return rows


def print_scrub(runs):
    print(
        "\n## Thread scrub (cache paths out of 30 per run; range and total over runs)\n"
    )
    print("| Between the worker's exit and the launch | Range | Total |")
    print("|---|---:|---:|")
    for label, key in scrub_rows():
        vals = values(runs, "thread-scrub", key)
        if vals:
            print(f"| {label} | {fmt_range(vals)} | {sum(vals)}/{30 * len(vals)} |")


def print_filesystems(runs):
    print("\n## Filesystems (exited-cache-worker cells combined, out of 60, per run)\n")
    fs_runs = [r for r in runs if "filesystem-images" in r["summaries"]]
    labels = sorted(
        {label for r in fs_runs for label in r["summaries"]["filesystem-images"]}
    )
    print(
        "| Volume | " + " | ".join(f"Run {i + 1}" for i in range(len(fs_runs))) + " |"
    )
    print("|---|" + "---:|" * len(fs_runs))
    for label in labels:
        cells = []
        for r in fs_runs:
            s = r["summaries"]["filesystem-images"].get(label)
            cells.append(
                str(
                    s["hardlink/cache-dead/spawn"]["cache_path"]
                    + s["hardlink/cache-dead/exec"]["cache_path"]
                )
                if s
                else ""
            )
        print(f"| {label} | " + " | ".join(cells) + " |")
    other = []
    for r in fs_runs:
        for label, s in r["summaries"]["filesystem-images"].items():
            other += [
                (r["id"], label, k, v["cache_path"])
                for k, v in s.items()
                if v["cache_path"] and "hardlink/cache-dead" not in k
            ]
    print(f"\nNonzero cells outside the exited-cache-worker cells: {other or 'none'}")


def print_route2(runs):
    print("\n## Route two (cache paths out of 30, per run)\n")
    r2 = [r for r in runs if "route2-images" in r["summaries"]]
    print(
        "| Lookup while the child is suspended | Host APFS | APFS image | HFS+ image |"
    )
    print("|---|---:|---:|---:|")
    for op, label in ROUTE2:
        cells = [
            ", ".join(
                str(r["summaries"]["route2-images"][fs][f"hardlink/{op}"]["cache_path"])
                for r in r2
            )
            for fs in VOLUMES
        ]
        print(f"| {label} | " + " | ".join(cells) + " |")
    copies = sum(
        r["summaries"]["route2-images"][fs][k]["cache_path"]
        for r in r2
        for fs in VOLUMES
        for k in r["summaries"]["route2-images"][fs]
        if k.startswith("copy")
    )
    print(f"| Any, copied executable | {copies} total over {len(r2)} runs | | |")


def host(runs, job):
    """macOS version, dyld project, and architecture recorded for a job."""
    for run in runs:
        lines = run["hosts"].get(job)
        if lines:
            version = next(
                line.split()[-1] for line in lines if line.startswith("ProductVersion")
            )
            dyld = next(
                line.split("dyld-")[-1] for line in lines if "PROJECT:dyld" in line
            )
            return version, dyld, lines[-1]
    return "?", "?", "?"


def print_images(runs):
    print(
        "\n## Runner images (exited-cache-worker cells, out of 40; range over runs)\n"
    )
    print(
        "| Image | macOS | dyld | Arch | Runs | `spawn` | `exec` | Nonzero elsewhere |"
    )
    print("|---|---|---|---|---:|---:|---:|---|")
    for os_ in ["macos-15", "macos-15-intel", "macos-26", "macos-26-intel"]:
        job = f"thread-exit-{os_}"
        spawn = values(runs, job, "hardlink/cache-dead/spawn")
        exec_ = values(runs, job, "hardlink/cache-dead/exec")
        version, dyld, arch = host(runs, job)
        print(
            f"| `{os_}` | {version} | {dyld} | {arch} | {len(spawn)} | {fmt_range(spawn)} "
            f"| {fmt_range(exec_)} | {nonzero_elsewhere(runs, job, 'hardlink/cache-dead')} |"
        )
    total = dead = paths = 0
    for r in runs:
        for job, s in r["summaries"].items():
            for k, v in s.items():
                if job.startswith("thread-exit-") and k.startswith("clone"):
                    total += v["launches"]
                    paths += v["cache_path"]
                    dead += v["launches"] if "cache-dead" in k else 0
    print(
        f"\nClone launches: {total} total, {dead} in exited-cache-worker cells, {paths} cache paths."
    )


def print_link_cost(runs):
    print(
        "\n## Link cost (median seconds per run; clone_per_file used cp before run 41829764653)\n"
    )
    for method in [
        "hardlink",
        "clone_per_file",
        "copy_per_file",
        "clone_tree",
        "copy_tree",
    ]:
        print(f"- {method}: {values(runs, 'link-cost', method, 'median_seconds')}")


def print_installers(runs):
    print("\n## Installers\n")
    for r in runs:
        s = r["summaries"].get("installer-identity")
        if s:
            cells = [
                f"{k}: nlink {v['nlink']}, shares inode {bool(v['shares_inode_with_cache'])}, cache matches {v['cache_matches']}, failures {v['failures']}/{v['launches']}"
                for k, v in s.items()
            ]
            print(f"- run {r['id']}: " + "; ".join(cells))


def print_retry(runs):
    print("\n## Retry on a retained inode\n")
    for r in runs:
        for k, v in (r["summaries"].get("retained-inode-retry") or {}).items():
            print(f"- run {r['id']} {k}: {json.dumps(v)}")


def main():
    runs = json.load(open(sys.argv[1]))["runs"]
    for section in [
        print_runs,
        print_cross_process,
        print_scrub,
        print_filesystems,
        print_route2,
        print_images,
        print_link_cost,
        print_installers,
        print_retry,
    ]:
        section(runs)


if __name__ == "__main__":
    main()
