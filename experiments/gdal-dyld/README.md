# macOS loader experiments on GitHub Actions

> [!WARNING]
> **AI-generated investigation.** This document, the experiments it
> describes, and the code in this directory were produced by Claude Fable
> 5.1 using Claude Code and by GPT-6 Astra using Codex, at the direction of
> Ben Mares (maresb), who does not understand the technical details and
> cannot vouch for them independently.

The fork-only workflow runs on GitHub-hosted `macos-latest` arm64 runners in
`maresb/conda-lock`. Push this directory or its workflow on
`investigate/gdal-dyld-ci` to run it. No pull request is needed.

- [TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) records the spontaneous reproduction
  and its connection to the controlled experiments. The workflow changes across
  runs; its current revision runs `spawn_probe.py`, which suspends GDAL during
  a single cache lookup. Each report links the run and revision that produced it.
- The fresh-install run used `trigger_probe.py` on four independent runners,
  using the same `setup-micromamba` action, Micromamba 2.10.0, named environments,
  and home-directory cache location as the original failing job. Three runners
  each repeat the original three-environment sequence eight times under tracing.
  Only the first launch of each environment contributes to the primary count;
  failures are retried separately. The fourth runner exercises cache `open`,
  `stat`, `getattrlist`, and event-only opens on the actual GDAL executable and
  library, comparing hardlinked and copied executables. It checks the original
  libcrypto error signature and records unchanged library hashes and inodes.
- `natural_copy_probe.py` (job `natural-selective`, three instances) runs the
  real `micromamba create` sequence with only `bin/gdalinfo` replaced by a byte
  copy, or with a pause of 1 s or 2 s before the first launch, records which
  Mach-O files in the environment are hardlinked to the cache, and repeats
  `delay_probe.py`'s design with the real executable and with a hardlinked
  library as the trigger target.
- Later runs use that script's `--reader-backend spotlight` for real metadata
  import requests, and `link_state_probe.py` for sequential operations without
  a concurrent reader.
- The initial run, documented in `CI-RESULTS.md`, used `natural-gdal` with the
  original Micromamba 2.10.0 and public GDAL lock artifacts
  from conda/conda-lock run 41529182437. It performs 600 launches without tracing,
  then repeats 600 launches with a bounded `fs_usage` capture on the same private
  package cache. Each sequence creates unified-lock, explicit-lock, and YAML
  environments before launching them in that order. No artificial reader runs
  in this job. `analyze_trace.py` matches serial launches to trace events by order.
- That run's `controlled-loaders` job ran the standalone executable reproducer, selective-copy
  controls, library-only `open`/`stat` races, the inherited-RPATH comparison, and
  the held-descriptor path probe. It runs on a separate VM.

The library experiment always copies the executable. Its direct `@loader_path`
dependency prevents the executable's RPATH from concealing a wrong library path.
Each library-only trial uses fresh files and records its actual outcome.

A successful workflow means the experiment completed; deliberate loader failures
are recorded as data. The job summary and artifacts contain the measured cells,
OS/tool versions, raw events, and per-file checksums. Package caches and installed
environments are excluded from artifacts. Traces retain GDAL-related lines;
later captures also retain metadata-process context for calls without pathnames.

The filesystem capture is restricted in code to this fork's GitHub Actions jobs
and requires working runner sudo permissions. A failed or incomplete capture is
reported as an error. No security settings are changed.
