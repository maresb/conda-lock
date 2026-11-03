# macOS loader experiments on GitHub Actions

The fork-only workflow runs on GitHub-hosted `macos-latest` arm64 runners in
`maresb/conda-lock`. Push this directory or its workflow on
`investigate/gdal-dyld-ci` to run it. No pull request is needed.

- `natural-gdal` uses the original Micromamba 2.10.0 and public GDAL lock artifacts
  from conda/conda-lock run 41529182437. It performs 600 launches without tracing,
  then repeats 600 launches with a bounded `fs_usage` capture on the same private
  package cache. Each sequence creates unified-lock, explicit-lock, and YAML
  environments before launching them in that order. No artificial reader runs
  in this job. Timestamps and wrapper PIDs support correlation with trace events.
- `controlled-loaders` runs the standalone executable reproducer, selective-copy
  controls, library-only `open`/`stat` races, the inherited-RPATH comparison, and
  the held-descriptor path probe. It runs on a separate VM.

The library experiment always copies the executable. Its direct `@loader_path`
dependency prevents the executable's RPATH from concealing a wrong library path.
Each controlled trial uses fresh files and records its actual outcome.

A successful workflow means the experiment completed; deliberate loader failures
are recorded as data. The job summary and artifacts contain the measured cells,
OS/tool versions, raw events, and per-file checksums. Package caches and installed
environments are excluded from artifacts. Traces retain GDAL-related lines only.

The filesystem capture is restricted in code to this fork's GitHub Actions jobs
and requires working runner sudo permissions. A failed or incomplete capture is
reported as an error. No security settings are changed.
