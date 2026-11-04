# CI performance experiments

All product code, test code, dependency locks, and action pins are from PR #972
at b32d4e58b909cc9011684970f621f64f9fe73506. The original workflows are unchanged.

The fork-only push workflow selects its case from `case.env`. Cases are run
sequentially to avoid interference between their runner queues. Each case is
repeated to compare cold and warm environment caches, using a separate
environment cache prefix for each case. GDAL installations remain uncached
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

Generate the reusable benchmark workflows with `python experiments/ci-performance/generate.py`
(requires PyYAML). Only `case.env` changes between repeat runs.
