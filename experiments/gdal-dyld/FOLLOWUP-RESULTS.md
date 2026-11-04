# Exited-thread trigger: follow-up experiments, 2026-11-04

**A cache lookup by a worker that exits before launch is sufficient to reproduce
the original GDAL failure. Keeping that worker alive but idle prevents the
failure in the matched experiment. No concurrent cache reader is needed.**

All runs below used GitHub-hosted macOS 26.6.2 arm64 runners in `maresb/conda-lock`.
The initial [TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) remains the record of the
earlier spontaneous failure and suspended-start experiment.

## The decisive comparison

[Run 41807550182](https://github.com/maresb/conda-lock/actions/runs/41807550182),
commit `c2545b3717e271666b570b561ca6f1599d044757`, ran the original GDAL package
640 times. Every trial used a fresh cache-executable inode and either hardlinked
or copied it into the environment. In [prime_exec.c](prime_exec.c), one worker
calls `stat()` on the designated alias. The main thread then calls `stat()` on
the **environment** alias. The worker either exits and is joined, or remains
blocked without further filesystem activity. Only then does the launcher run
GDAL. Cases were shuffled with a fixed seed.

| Executable | Worker lookup | Worker at launch | `posix_spawn` failures | `execve` failures |
|---|---|---|---:|---:|
| Hardlink | Cache | Exited | 39/40 | 32/40 |
| Hardlink | Cache | Alive, idle | 0/40 | 0/40 |
| Hardlink | Environment | Exited or alive | 0/80 | 0/80 |
| Copy | Either | Exited or alive | 0/160 | 0/160 |

All 71 failures have the original missing-libcrypto message and cached-libgdal
UUID. All 640 launches match the trace in order: every failure's main-executable
`fsgetpath` names the cache, and all 569 successes name the environment. In the
retained complete-activity intervals between launch and that lookup, no
intervening cache- or environment-path lookup is reported. This is a finite
experiment, not a claim that cache-worker exit is the only possible trigger.

The nine passing cache/exited cases are not explained by these traces.
Different kernel allocation outcomes are a plausible explanation, not a
measured result.

## Why this fits the original failure

[Three more original-sequence jobs](https://github.com/maresb/conda-lock/actions/runs/41803396689)
produced **3/72 first-launch failures**, without artificial workers or requested
indexing. All three subsequently passed on retry. The failed launches used the
same wrong cache executable path and original library signature. Together with
the earlier fresh-install experiment, that is 4/144 first-launch failures.

The broader capture preserves every reported filesystem event around each
launch. Two failure intervals contain only the caller's `execve`/exit and
dyld's path lookups; the third also contains unrelated `warmd` activity. No
cache-path lookup appears between `execve` and the wrong `fsgetpath` result.
The last retained cache-executable access before each failure is Micromamba's
earlier installation activity. This strengthens the case for retained state;
it does not identify an individual recycled kernel object.

The traces show a different thread ID for the calling shell and the new GDAL
image. Apple's published [exec implementation](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_exec.c#L5426)
creates a new task and thread. Thus a lookup in the caller does not establish
the new executable thread's own lookup history.

## What the filesystem experiments establish

- [16,200 data-file observations](https://github.com/maresb/conda-lock/actions/runs/41803699556)
  show that inode-based `fsgetpath` can preserve the calling thread's alias
  while `F_GETPATH` follows a different thread's alias. This occurs on the
  runner's APFS volume, a new APFS image, and an HFS+ image, without executing
  the hardlinked file.
- [Eviction tests](https://github.com/maresb/conda-lock/actions/runs/41804850317)
  and [boundary checks](https://github.com/maresb/conda-lock/actions/runs/41805629288)
  show the original thread retaining its alias after seven other live threads
  look up the other alias on APFS, then losing it after eight. HFS+ retains it
  after eight and loses it after nine. Each tested point was repeated 20 times
  per filesystem. Workers remain alive, excluding thread reuse from this test.
- Link-ID-based `fsgetpath` returned the designated alias in all **2,160**
  queries across those two runs, including after eviction. The two aliases
  have the same file ID but different link IDs.
- The [sequential lookup controls](https://github.com/maresb/conda-lock/actions/runs/41805629288)
  reject a simple stale-fast-path explanation: making the original thread
  itself look up the intended alias refreshes its origin. Merely having
  another thread do so does not. All 4,800 observations match this distinction.

Apple's [HFS origin-cache implementation](https://github.com/apple-oss-distributions/hfs/blob/d1bac2f062e6e9c0dfcce302d9aacb10173d0eea/core/hfs_link.c#L1134)
keys entries on `current_thread()` pointers, bounds the number of entries, and
falls back to other stored file state when no matching origin exists. The
observed HFS eviction boundary agrees with that source's allocation condition.
APFS exhibits analogous behavior, but its implementation was not inspected.

**The leading explanation is reuse of a terminated worker's kernel thread
object, causing the new executable thread to match a stale cache-origin
entry.** Worker lifetime is experimentally isolated. The exact APFS key and
object reuse are inferred from behavior and the HFS implementation; no kernel
pointer or APFS origin entry was directly observed. Attribution of the original
sporadic failure to a particular Micromamba worker is likewise an inference.

## Other controls and limitations

The [fresh-inode worker-count experiment](https://github.com/maresb/conda-lock/actions/runs/41806789517)
preceded the lifetime comparison. Cache workers: one worker caused 17/20 exec
and 20/20 spawn failures; eight caused 17/20 and 18/20. Zero or 32 cache workers
caused none. Environment-worker cells had one failure in 160 launches; copies
had none in 80. The 32-worker result is consistent with eviction plus allocation
order, but does not establish that interaction. Its raw process results cover
400 launches, while only **388** have matching retained launch/path trace
records. Do not claim complete trace correlation for that exploratory run.

The earlier [sequential GDAL matrix](https://github.com/maresb/conda-lock/actions/runs/41805161951)
had 22/320 hardlinked launch failures and 0/320 copied failures, plus 320 API
probes. Its warmed-path controls were not reliable launch protections. All 640
actual launches correlate with the expected trace result.

The [three-alias startup experiment](https://github.com/maresb/conda-lock/actions/runs/41804100124)
also demonstrated silent loading from another environment: 99/310 hardlinked
launches returned that environment's library value; 107 aborted; 104 returned
the intended value. All 280 copied controls returned the intended value.
`_NSGetExecutablePath()` and the kernel's supplied launch path still named the
intended executable during wrong-library successes. These interleaved cells
are mechanism tests, not estimates of real-world failure rates.

## Consequences

Apple documents that [inode-based `fsgetpath` may return any hardlink alias](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/man/man2/fsgetpath.2#L64).
Its published [dyld main-path code](https://github.com/apple-oss-distributions/dyld/blob/fd8d0c4d52320ebf64db34f3cb280310d905c5ae/dyld/DyldProcessConfig.cpp#L656)
prefers that inode-based result over the kernel-supplied executable pathname.
The source revisions are evidence for the design, not an assertion that they
exactly match every component of the runner's dyld 1387 build.

Copying the affected executable avoids this hardlink ambiguity. Copying only
its libraries does not protect against selecting a cache-relative library.
Parent-thread warming and fixed delays cannot be justified as reliable fixes
by these results. Link IDs offer a more specific path identity, but making dyld
use one would require changes beyond these experiment scripts.

## Evidence

[followup-evidence.json](followup-evidence.json) records run/commit IDs, artifact
digests, reconciled counts, source links, and selected raw failure intervals.
Downloaded ZIP digests and manifest checksums were verified. Large traces were
checked by streaming; local analysis copies retain only GDAL-executable lines,
explicitly marked as derived data. Relevant full-activity windows were read
directly from the original ZIPs. Empty trace stderr alone does not prove that
every event was retained; ordered count checks are reported separately above.
Artifacts expire around 2026-12-04; selected evidence is committed here.
