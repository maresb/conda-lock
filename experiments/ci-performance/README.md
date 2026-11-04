# CI performance experiments

All product code, test code, dependency locks, and action pins are from PR #972
at b32d4e58b909cc9011684970f621f64f9fe73506. The original workflows are unchanged.

The fork-only push workflow selects its case from `case.env`. Cases are run
sequentially where possible to avoid interference between their runner queues.
Cold and warm environment-cache cases use a separate environment cache prefix
for each variant. GDAL installations remain uncached
between jobs, matching the original workflow.

Baseline uses the original integration graph and 3/10/10 pytest shards per
Python version on Linux/macOS/Windows. Candidate uses independent OS/Python
integration pipelines, disables setup-miniconda post cleanup, splits Windows
conda-lock installation across the three lockfile formats, and uses 3/4/4 shards.
Both Python versions and every existing test and installation check remain.

Pytest still uses coverage and pytest-xdist. Both cases omit the external
Codecov upload; coverage generation, duration uploads, aggregation, and status
checks remain. Queue time and runner execution time must be reported separately.
Fork queue behavior is not assumed to match the conda organization.

GitHub reported an Actions outage starting at 16:05 UTC on November 4. The first
baseline run completed its Linux/Windows jobs while all macOS jobs stayed queued.
The candidate was therefore started as a correctness diagnostic before that
baseline finished. Neither outage-era run provides a clean end-to-end speed
comparison. Performance repetitions must run sequentially after recovery.

The `windows-control` case isolates installation concurrency from that macOS
blocker. One Windows/Python 3.14 producer supplies identical lockfiles to two
serial controls and two three-format parallel batches. The serial controls keep
the original post cleanup; the parallel batches disable it. Job step durations
separate the install concurrency effect from post-cleanup time. Every consumer
starts with a fresh runner, so all formats incur their own cold package download.

The `windows-baseline`, `windows-candidate`, `macos-baseline`, and
`macos-candidate` cases run only that platform's pytest matrix. They reuse the
respective full case's environment cache prefix, allowing sequential sharding
comparisons without unrelated platforms or integration jobs in the runner queue.

Generate the reusable benchmark workflows with `python experiments/ci-performance/generate.py`
(requires PyYAML). Only `case.env` changes between repeat runs.

## Measured results, November 4, 2026

The original PR #972 integration run took **10m35s**, from workflow creation to
the final successful status job. Its pytest workflow took **5m08s**. These
experiments do not establish a new full-workflow completion time: macOS arm64
capacity prevented the macOS cases from executing.

### Windows installation: two controls and two parallel batches

[Run 41870597877](https://github.com/maresb/conda-lock/actions/runs/41870597877)
passed all installation checks. One producer supplied identical lockfiles to
every consumer. Consumer runners were fresh, with no shared package cache.

| Repeat | Serial consumer | Three-format parallel batch | Serial runner-minutes | Parallel runner-minutes |
| --- | ---: | ---: | ---: | ---: |
| 1 | 8m11s | 4m14s | 8.18 | 11.73 |
| 2 | 6m24s | 4m16s | 6.40 | 12.40 |

Parallel batch duration spans the earliest consumer start to the latest finish.
Mean latency fell **41.7%** (7m17.5s to 4m15s), while consumer runner time rose
**65.5%**. Producer/configuration time is excluded from both comparisons.
The serial controls spent 25s and 15s in Miniconda post cleanup; the parallel
jobs had none. Install/check steps took 341s and 253s serially, versus maximum
per-format steps of 134s and 145s. This isolates the large install-concurrency
benefit from the smaller cleanup benefit, without treating the two controls as
a statistically precise population estimate.

### Windows pytest: sequential warm-cache comparison

| Case | Shards per Python | Matrix wall time | Pytest runner-minutes | Environment setup total |
| --- | ---: | ---: | ---: | ---: |
| [Baseline](https://github.com/maresb/conda-lock/actions/runs/41872657150) | 10 | 3m13s | 44.52 | 14m42s |
| [Candidate](https://github.com/maresb/conda-lock/actions/runs/41873484019) | 4 | 4m05s | 25.67 | 5m20s |

Both Python 3.11 and 3.14 passed. Every job restored its environment cache:
20/20 baseline and 8/8 candidate. The final timing artifacts contain exactly
the same 344 test IDs for each Python version. The earlier four-shard cold run
also had 344 unique IDs per Python, with no duplicated or omitted IDs across
its raw shard artifacts.

Reducing Windows shards saved **42.3%** of pytest runner time but added **52s**
to matrix wall time. This is a cost tradeoff, not a standalone latency win.
Whole experiment times, including configuration, queueing, aggregation, and
status, were 3m53s and 5m01s. A single sequential warm pair is sufficient to
demonstrate this observed tradeoff, but does not establish a stable latency
distribution. Fork queue behavior is not a measurement of organization queues.

### Integration dependencies and blocked macOS measurements

In [the candidate diagnostic](https://github.com/maresb/conda-lock/actions/runs/41869373609),
all Linux/Windows pytest and integration jobs passed while macOS producers
remained queued. Each integration consumer started 2–4s after its own producer
finished, demonstrating that the independent pipelines remove the global
cross-platform dependency barrier. The original Windows/Python 3.14 producer
finished 87s before the final macOS producer, so the original graph imposed
87s of unnecessary dependency waiting before runner acquisition.

The original-graph diagnostic was also blocked by macOS. Five Linux/Windows
test jobs failed on external conda-forge HTTP 502 responses or repodata
timeouts. Those runs were retained as diagnostics and cancelled after the
non-macOS work finished; their overall times are not valid comparisons.

A fresh [macOS availability probe](https://github.com/maresb/conda-lock/actions/runs/41871963179)
targeted both `macos-latest` and `macos-26`. Neither received a runner; both
failed after approximately 15 minutes. GitHub annotations explicitly reported
macOS arm64 capacity constraints and failure to acquire a hosted runner. This
is distinct from the concurrent general Actions incident, which was resolved
by the final status check. No macOS shard-count recommendation is validated by
these experiments. The macOS comparison and a complete candidate integration
run remain outstanding until runner capacity is available.

## Recommended next changes

1. Use independent OS/Python integration pipelines and disable Miniconda post
   cleanup on these disposable runners. The dependency fix has no added test
   matrix cost; cleanup removal saves measured runner time.
2. Split the Windows conda-lock format checks to reduce critical-path latency,
   accepting their extra runner cost. After that, the direct Windows
   micromamba/conda installation checks can become the next bottleneck.
3. Consider four Windows pytest shards to save runner time, accepting the
   observed extra 52s for that matrix. Full-CI latency impact needs the complete
   candidate graph to finish; do not claim a measured end-to-end improvement.
4. Keep the refreshed duration seeds and finish #969's upstream safeguards,
   shared-template changes, and action-pin update. Its automated refresh keeps
   shard estimates current; it does not remove integration dependencies or
   serial installation work. Defer the macOS shard change until measured.

`results.json` and `job-timings.csv` record the successful control measurements.
The original product code, tests, dependencies, and standard workflows remain
unchanged. No pull request was opened.

## Resource measurements

Run `python experiments/ci-performance/instrument.py` to regenerate workflows
with resource sampling. This first regenerates the ordinary experiment variants.
The sampler uses pinned psutil 7.1.0 in a separate Python 3.11 environment and
records system-wide per-logical-CPU utilization, disk and network counters,
available memory, and sampled CPU deltas grouped by process name once a second.
It records a five-second idle baseline and labels each subsequent workflow step.
The `cpu-probe` mode validates the readings against eight seconds of known CPU
load on each platform before real workload measurements.

Resource artifacts have unique names and are excluded from pytest duration
aggregation. Sampler CPU time is recorded to quantify instrumentation overhead.
Sampling covers environment setup and tests/installations, ending before artifact
upload and post-job cleanup. It excludes checkout, telemetry environment setup,
and runner queueing. Process deltas miss processes that start and finish between
samples, so system-wide CPU is the authoritative utilization measure. Disk and
network counters describe activity, not proof that either device is saturated.
Phase boundaries have approximately one-second sampling uncertainty.
