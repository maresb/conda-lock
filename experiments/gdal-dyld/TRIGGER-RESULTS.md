# Connection to the original GDAL failure

**The original install/launch sequence reproduced the failure without an
artificial reader or requested indexing. Its trace identifies the same wrong
executable-path lookup as the controlled reproducer.**

[Failing launch's CI job](https://github.com/maresb/conda-lock/actions/runs/41735120410/job/126262207838)
at commit `6bf79f89e276555951785eb933c062f7c59fadda`, macOS 26.6.2, dyld 1387,
Micromamba 2.10.0. All experiments ran on GitHub-hosted runners in this fork.

Three independent runners each performed eight repetitions of the original
unified-lock, explicit-lock, YAML installation sequence. Among the 72 first
launches, one failed: the unified-lock environment in repetition 5 on runner 3.
The other environments launched successfully, and a subsequent retry of the
failed environment also succeeded.

The failing launch, in `fs_usage`'s own clock:

| Time (UTC) | Observation |
|---|---|
| 23:05:06.670259 | `execve` names `envs/gdal-test-mm-lock/bin/gdalinfo`. |
| 23:05:06.670835 | `fsgetpath` returns `pkgs/.../libgdal-3.6.2-h51eea9d_5/bin/gdalinfo`. |
| 23:05:06.671028 | The loader opens that cached executable pathname. |
| 23:05:06.671706 | Loading libcrypto fails; subsequent searches use cache-relative paths. |

The resulting dyld error names the same missing `@rpath/libcrypto.3.dylib`,
cached `libgdal.32.3.6.2.dylib`, and UUID
`042BC0C2-C636-39C6-8DFD-3580A4847EF8` as the original upstream job.
Post-launch inspection confirms that the environment executable and cache
executable share an inode and identical bytes. The environment's `libgdal` is
already a separate, relocated file: copying the library alone cannot prevent
the loader from choosing the cache-relative library after misidentifying the
executable path.

[natural-trigger.json](natural-trigger.json) preserves the raw failing event,
trace excerpt, file identities, retry, source artifact ID, and ZIP checksum.

## A single cache lookup is sufficient at the controlled boundary

[Suspended-start experiment](https://github.com/maresb/conda-lock/actions/runs/41738239207/job/126272883668)
uses `POSIX_SPAWN_START_SUSPENDED` to pause the real GDAL process before dyld
startup, performs one lookup in its parent, and resumes it with `SIGCONT`.
The library and executable bytes are unchanged.

| Operation while the child is suspended | Hardlinked executable | Copied executable |
|---|---:|---:|
| One cache `open()` followed by `close()` | 20/20 fail | 0/20 fail |
| One cache `stat()` | 20/20 fail | 0/20 fail |
| No lookup | 3/20 fail | 0/20 fail |
| Cache `open()`, then installed-path `open()` | 4/20 fail | 0/20 fail |
| Cache `open()`, then installed-path `stat()` | 4/20 fail | 0/20 fail |

Every failure has the original libcrypto signature and a cache-returning main
`fsgetpath`; every success resolves to the environment. This establishes the
effect of a single cache-alias lookup at that boundary, without a busy reader
loop. The nonzero controls also show that warming the installed pathname is not
a reliable workaround. Copying the executable passes all 100 controls.
[suspended-trigger.json](suspended-trigger.json) preserves a single-`stat` case.

## Controlled follow-ups

| Experiment | Outcome |
|---|---|
| [Actual GDAL, cache syscall readers](https://github.com/maresb/conda-lock/actions/runs/41735475088) | `open`, event-only open, and `getattrlist` on cached executable: each 20/20 failures. `stat`: 18/20. All 180 copied-executable controls pass. |
| Same reader run, other cells | No active reader: 5/20 hardlinked launches fail. Library-targeted readers: 6/80 fail; those failures also resolve the **executable** to its cache alias. |
| [Real metadata import requests](https://github.com/maresb/conda-lock/actions/runs/41735870560) | Hardlinks: import 30/80, test-import 30/80, no active import 32/80 failures. Copies: 0/240. |
| [Sequential operations, no reader](https://github.com/maresb/conda-lock/actions/runs/41736714181) | 0/520 failures across pristine launches, relinking, cache reads, and installed-path warming. |

All 89 primary failures in the syscall-reader run match the original GDAL error;
81 pass on the first retry after stopping the reader. Its trace has 449 matched
launches including retries. Every failure resolves the executable to the cache,
and every successful launch resolves it to the environment. The metadata-import
run has the same correspondence across 572 launches including retries.

The metadata experiment also captures a real system process in the relevant
interval. In `hardlink/app/import`, trial 15:

```text
23:03:05.787584  execve     envs/gdal-trigger-reader/bin/gdalinfo
23:03:05.788299  open       pkgs/.../bin/gdalinfo                  mds.814
23:03:05.788314  fsgetpath  pkgs/.../bin/gdalinfo                  gdalinfo.11730
```

This is evidence that real metadata activity can participate in the same race.
[metadata-trigger.json](metadata-trigger.json) preserves this case's raw records.
It is **not proof that Spotlight caused the spontaneous failure**. Import
requests are asynchronous and can affect later cells, so the similar rates in
the interleaved import/no-import cells are not an isolated causal comparison.

## What remains unresolved

The spontaneous trace locates the divergence at `fsgetpath()`, but does not
identify why that lookup chose the cache alias. Its last retained cache-binary
access before launch is Micromamba's `link` call about 1.64 seconds earlier;
no retained cache-file access falls between `execve` and `fsgetpath`. That
capture filtered pathname-less metadata calls, so absence of such an access
does not exclude other filesystem activity. Later captures retain metadata
process context as well.

Thus the connection between the artificial reproducer and the original GDAL
failure is observed directly. The exact kernel/filesystem state or background
activity selecting the alias in the spontaneous case remains open.

## Verification and rerunning analysis

All downloaded ZIP digests matched GitHub's artifact digests, and all file
checksums matched their manifests. The raw launch records reproduce the summary
counts. `analyze_trace.py` matches launches, `execve`, and main `fsgetpath` events
by order (also supporting `posix_spawn`), with assertions on counts and ordering;
it does not equate Python's
wall clock with the trace clock. Numeric process-name suffixes in `fs_usage`
are thread IDs, not the PIDs in the probe records.

```sh
python3 experiments/gdal-dyld/analyze_trace.py /path/to/unpacked/artifact
```

The initial setup-only failure and interrupted reader matrix are excluded from
the counts above. The natural jobs in run 41735120410 succeeded independently
of its interrupted reader job; the corrected reader matrix is run 41735475088.
Artifacts expire after 30 days; the selected spontaneous trace is retained here.
