# GitHub-hosted macOS experiment, 2026-11-03

Follow-up: [TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) captures a spontaneous failure
in the original install sequence and connects it to the wrong `fsgetpath` result.

Run: <https://github.com/maresb/conda-lock/actions/runs/41727749639>

Experiment commit: `3ba4c3fadaced4e27d89bcb17771f9aae065754f`.
Both jobs ran on GitHub's `macos-26-arm64` image: macOS 26.6.2
(25G83), arm64, dyld 1387, Apple clang 21.0.0. These results come exclusively
from this fork's GitHub-hosted runner.

## Controlled experiments

[Job and logs](https://github.com/maresb/conda-lock/actions/runs/41727749639/job/126236868544),
artifact `gdal-controlled-evidence` (ID `13274177714`).

| Experiment | Failures / launches |
|---|---:|
| Standalone: hardlinked executable, no reader | 1/30 |
| Standalone: hardlinked executable, concurrent cache reader | 30/30 |
| Standalone: copied executable, concurrent cache reader | 0/30 |
| Library: hardlinked outer library, cache `open()` loop | 39/60 |
| Library: hardlinked outer library, cache `stat()` loop | 13/60 |
| Library: hardlinked outer library, no reader | 0/60 |
| Library: copied outer library, all three reader conditions | 0/180 |

The library experiment always copies the executable. Its inner dependency uses
`@loader_path/private/libinner.dylib`, so an executable RPATH cannot rescue a
lookup relative to the wrong outer-library path. Failures name the cached outer
library and look for the inner library relative to that cache path. Both linked
startup and `dlopen()` fail: respectively 19/30 and 20/30 with `open()`, and
6/30 and 7/30 with `stat()`. Every active reader recorded successful operations;
raw inode records confirm hardlink/copy assignments and executable link count 1.

With the older `@rpath` layout, all 60 launches pass, but `dladdr()` reports the
cached outer-library path in 29 of them (linked 10/30; `dlopen()` 19/30).
The inherited executable RPATH can therefore conceal a wrong library path.
Separate forced-cache controls confirm that the direct layout fails and the
RPATH layout succeeds when explicitly loading the cached outer library.

The selective-copy matrix adds 480 launches. All 118 failures occur while the
executable remains hardlinked and the reader opens its cache alias. Copying the
executable gives 0/240 failures; copying only the library does not protect the
executable. The simpler layout's library-only reader produces no failures, which
must be interpreted alongside the masking result above. The 72 initial fixture
control launches all pass. Across these probes there are 1,062 measured launches,
plus the two forced-cache controls.

The held-descriptor probe opens the environment hardlink once, keeps that
descriptor open, and alternates opening the two aliases. Both `F_GETPATH` on the
held descriptor and inode-based `fsgetpath()` return the most recently opened
alias: cache in 500/500 cache-last iterations and environment in 500/500 env-last
iterations. This demonstrates pathname instability in these APIs; it does not
by itself prove the precise dyld call responsible for each failure.

The smallest standalone reproduction is:

```sh
python3 experiments/gdal-dyld/reproduce.py
```

It requires macOS and Xcode Command Line Tools, and has no Conda dependency.
The workflow records commands for the other probes.

## Original GDAL sequence and filesystem trace

[Job and logs](https://github.com/maresb/conda-lock/actions/runs/41727749639/job/126236867728),
artifact `gdal-natural-evidence` (ID `13275103716`).

Micromamba 2.10.0 installed the original public GDAL package fixtures. The
untraced sequence had **0/600 failures**; the traced sequence also had **0/600**.
Every launch printed `GDAL 3.6.2, released 2023/01/02`. Each phase creates six
environments (two repetitions of unified, explicit, YAML) and launches each
environment 100 times. This is 1,200 launches, not 1,200 fresh installations.
The traced phase runs second and reuses the package cache, so this is not a
randomized measurement of tracing's effect on the failure rate.

The capture remained alive through the entire command. Its stderr is empty;
no buffer overrun was reported. It retained 788,587 GDAL-related lines, including
600 `execve` records. All six creation intervals and all 600 launch intervals
fall within the capture. Raw event times, not collector receipt times, were used
to compare cache accesses against launch intervals.

`mds` and `mdworker_shared` both open the cached `bin/gdalinfo` at approximately
22:13:14 UTC. The first launch command starts at 22:13:33.978 UTC, about 20 seconds
later. No retained cached-`gdalinfo` access falls inside a measured launch
interval. One `mds` `getattrlist` on cached `libgdal` does fall inside a launch
interval; that launch succeeds. These observations identify background cache
activity, but **do not identify the cause of the original sporadic failure**.
The numeric suffixes in `fs_usage` output are thread IDs, not the wrapper PIDs
recorded in the probe events.

## Evidence verification

The downloaded controlled artifact ZIP has SHA-256
`c29a673ffc55f3d22874f1bebf00c606832c86b78e6fc5e0babb6b27f7371de5`, matching
GitHub's artifact digest. All 33 file checksums match its manifest. Recounting the
raw JSONL events reproduces all four cell summaries exactly (72, 480, 360, and 60
events). The standalone counts and held-descriptor results come from their logs.

The natural artifact ZIP has SHA-256
`4f9ebb07aae0746ec654fb28cd8c3b5454882e01ff1884da04ac88cffc0bce34`, matching
GitHub's artifact digest. All 34 file checksums match its manifest, and the raw
events reproduce both 600-launch summaries. Artifacts are retained for 30 days;
the scripts and this report remain on the experiment branch.

These are finite, single-run samples. The controlled reader establishes a
reproducible trigger; it does not identify which process causes the original
sporadic GDAL failure.
