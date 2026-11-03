#!/usr/bin/env python3
"""Correlate serial GDAL launches with fs_usage in an unpacked CI artifact.

Each launch must have one execve/posix_spawn and one main-executable fsgetpath.
Match by order: fs_usage and Python wall-clock timestamps can drift apart.
Reject missing, overlapping, or midnight-crossing sequences instead of guessing.
"""

import argparse
import bisect
import collections
import json

from pathlib import Path


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("artifact_directory", type=Path)
p = parser.parse_args().artifact_directory
probe = p / ("probe" if (p / "probe").exists() else "traced")
events = [
    json.loads(line) for line in (probe / "events.jsonl").read_text().splitlines()
]
launches = [e for e in events if e["event"] == "launch"]
execs = []
mains = []
cache = []


def micros(s):
    h, m, s = s.split(":")
    a, b = s.split(".")
    return ((int(h) * 60 + int(m)) * 60 + int(a)) * 10**6 + int(b)


for raw in (p / "trace/events.jsonl").open():
    s = json.loads(raw)["line"]
    v = s.split()
    if len(v) < 3:
        continue
    if "/bin/gdalinfo " not in s:
        continue
    t = micros(v[0])
    op = v[1]
    actor = v[-1].rsplit(".", 1)[0]
    r = {"time_us": t, "line": s, "actor": actor, "op": op}
    if op in {"execve", "posix_spawn"}:
        execs.append(r)
    if actor == "gdalinfo" and op == "fsgetpath":
        mains.append(r)
    if "/pkgs/" in s and actor != "gdalinfo":
        cache.append(r)
assert len(execs) == len(mains) == len(launches), (
    len(execs),
    len(mains),
    len(launches),
)
assert all(a["time_us"] <= b["time_us"] for a, b in zip(execs, mains))
assert all(a["time_us"] < b["time_us"] for a, b in zip(mains, execs[1:]))
cache.sort(key=lambda x: x["time_us"])
times = [e["time_us"] for e in cache]
counts = collections.Counter()
failures = []
for e, x, m in zip(launches, execs, mains):
    key = (
        e["case"],
        e.get("retry", False),
        e["returncode"],
        "cache" if "/pkgs/" in m["line"] else "environment",
    )
    counts[key] += 1
    if e["returncode"]:
        nearby = cache[
            max(0, bisect.bisect_left(times, x["time_us"]) - 2) : bisect.bisect_right(
                times, m["time_us"]
            )
        ]
        failures.append({"launch": e, "exec": x, "main": m, "cache_accesses": nearby})
print(
    json.dumps(
        [
            {"case": k[0], "retry": k[1], "rc": k[2], "path": k[3], "count": v}
            for k, v in sorted(counts.items())
        ],
        indent=2,
    )
)
for f in failures:
    e = f["launch"]
    if e["case"].endswith("/none"):
        print(
            "NO ACTIVE READER",
            e.get("trial"),
            e.get("retry"),
            f["exec"]["line"],
            f["main"]["line"],
            sep="\n",
        )
        for a in f["cache_accesses"]:
            print(a["line"])
(p.parent / (p.name + "-ordered.json")).write_text(
    json.dumps(
        {
            "counts": [
                {"case": k[0], "retry": k[1], "rc": k[2], "path": k[3], "count": v}
                for k, v in sorted(counts.items())
            ],
            "failures": failures,
        },
        indent=2,
    )
    + "\n"
)
