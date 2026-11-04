# Exited-thread trigger: follow-up experiments, 2026-11-04

**A lookup of the package-cache alias by a thread that has since exited is
sufficient to make dyld resolve a hardlinked executable to the cache path.
The lookup can come from a separate, already-finished process. Keeping the
looking-up thread alive prevents it, and so do seven later lookups of the
environment alias by other live threads. The effect is present on macOS 15 and
26, on arm64 and x86_64, on APFS volumes, on APFS disk images, and on HFS+
disk images in all but one image-run. Copied and cloned executables never
resolve to the cache. After a wrong-path launch, every retry of the same
inode passed, and a pause of half a second or more before the first launch
left at most one wrong-path launch in twenty on these hosted runners. A stale
thread without a record follows the most recent lookup or path build by any
thread, alive or exited; the stale answer is replaced when its holder looks
up the environment alias and is gone within a second after the identity is
freed, which thread turnover in another process does not accelerate. Why
retries and pauses help is not established.**

All runs used GitHub-hosted runners in `maresb/conda-lock`. The earlier
[TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) records the spontaneous failures and
the suspended-start experiment. Run and artifact identifiers, host versions,
artifact digests, and every summary table in this document are collected in
[followup-evidence.json](followup-evidence.json), which covers every run of
the follow-up workflow, including cancelled runs with a note on what was
cancelled and by whom where known, plus the lifecycle and standalone runs
cited below.
Every table below is pasted from the output of
[summarize_evidence.py](summarize_evidence.py) on that record. Each summary
was recounted from its raw `events.jsonl`, and each artifact's file checksums
were verified against its manifest. Artifacts expire around 2026-12-04.

Two routes to the wrong executable path are now demonstrated separately:

1. **Stale origin, no concurrency.** A thread looks up the cache alias and
   exits. The launched process's first thread can inherit that lookup's
   per-inode origin record, so dyld's inode-based `fsgetpath` returns the cache
   path even though nothing touches either alias during the launch.
2. **Concurrent lookup.** Any lookup of the cache alias by any thread between
   `execve` and dyld's `fsgetpath`, a window of roughly half a millisecond,
   flips the fallback answer for a thread with no origin of its own
   (suspended-start experiment, 20/20 with one `stat`).

## The decisive comparison: live versus exited worker

[Run 41807550182](https://github.com/maresb/conda-lock/actions/runs/41807550182),
commit `c2545b37`, ran the original GDAL package 640 times under `fs_usage`
tracing. Every trial used a fresh cache-executable inode and either hardlinked
or copied it into the environment. In [prime_exec.c](prime_exec.c), one worker
calls `stat()` on the designated alias. The main thread then calls `stat()` on
the **environment** alias. The worker either exits and is joined, or remains
blocked without further filesystem activity. Only then does the launcher run
GDAL.

| Executable | Worker lookup | Worker at launch | `posix_spawn` failures | `execve` failures |
|---|---|---|---:|---:|
| Hardlink | Cache | Exited | 39/40 | 32/40 |
| Hardlink | Cache | Alive, idle | 0/40 | 0/40 |
| Hardlink | Environment | Exited or alive | 0/80 | 0/80 |
| Copy | Either | Exited or alive | 0/160 | 0/160 |

All 71 failures have the original missing-libcrypto message and cached-libgdal
UUID. Every failure's main-executable `fsgetpath` names the cache and all 569
successes name the environment. In the complete-activity trace windows between
each launch and that lookup, no process touched either alias. The traces also
show a different thread ID for the calling thread and the new GDAL image;
Apple's [exec implementation](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_exec.c#L5426)
creates a new task and thread with `cloneproc`, so an `execve` caller's own
lookup history does not carry over.

The same comparison without Conda, tracing, or a crash
([reproduce_thread_exit.py](reproduce_thread_exit.py), a 40-line program that
prints `_NSGetExecutablePath()` and `_dyld_get_image_name(0)`) gives 39/40 and
38/40 cache paths in the exited-cache-worker cells and 0/560 elsewhere
([run 41816421984](https://github.com/maresb/conda-lock/actions/runs/41816421984)).
In every wrong launch the kernel-supplied launch path is still the environment
path; only dyld's reconstructed main-image path is wrong.

## The lookup can come from another process

[reproduce_cross_process.py](reproduce_cross_process.py) models the installer
as a separate process ([touch_exit.c](touch_exit.c)) that looks up the cache
alias from its main thread or from one or four short-lived workers, then
exits. The environment alias is then launched either directly from Python
(fork and exec) or through a launcher process whose main thread first looks up
the environment alias, like a shell's PATH search, and then spawns or execs.
Fresh inode per trial, 30 trials per cell; cache paths chosen, as the range
over independent runs:

| Finished process looked up cache from (8 runs) | Python launches directly | Launcher spawns | Launcher execs |
|---|---:|---:|---:|
| Nothing (control) | 0 | 0 | 0 |
| Its main thread | 0 to 5 | 21 to 25 | 14 to 28 |
| One exited worker | 19 to 29 | 1 to 8 | 0 to 10 |
| Four exited workers | 24 to 29 | 1 to 12 | 3 to 11 |
| Any, copied executable | 0/2880 total | | |

The rates swap between the direct and launcher columns depending on which
threads exited last. That is consistent with reuse of recently freed kernel
thread objects, with an intermediate process consuming the most recently freed
one before the launched thread is created, but neither the objects nor the
allocation order were observed. The `micromamba create` then `micromamba run`
sequence corresponds to the launcher columns.

## What happens between exit and launch

[scrub_probe.py](scrub_probe.py) with [scrub_exec.c](scrub_exec.c) keeps the
exited cache worker and varies what follows, 30 trials per cell on macOS 26.6.2;
cache paths out of 30 as the range and total over independent runs (the
matched controls were added in later runs):

| Between the worker's exit and the launch | Range | Total |
|---|---:|---:|
| Nothing, `spawn` | 25 to 30 | 259/270 |
| Nothing, `exec` | 26 to 30 | 256/270 |
| 1 dummy threads created and joined | 17 to 28 | 218/270 |
| 2 dummy threads created and joined | 12 to 23 | 167/270 |
| 4 dummy threads created and joined | 15 to 21 | 162/270 |
| 8 dummy threads created and joined | 13 to 21 | 155/270 |
| 1 holder threads kept alive | 2 to 16 | 69/270 |
| 2 holder threads kept alive | 0 to 1 | 3/270 |
| 4 holder threads kept alive | 0 | 0/270 |
| 1 live threads that looked up the environment alias before the worker exited | 27 to 30 | 264/270 |
| 3 live threads that looked up the environment alias before the worker exited | 29 to 30 | 266/270 |
| 5 live threads that looked up the environment alias before the worker exited | 28 to 30 | 265/270 |
| 6 live threads that looked up the environment alias before the worker exited | 29 to 30 | 268/270 |
| 7 live threads that looked up the environment alias before the worker exited | 0 | 0/270 |
| 8 live threads that looked up the environment alias before the worker exited | 0 | 0/270 |
| 10 live threads that looked up the environment alias before the worker exited | 0 | 0/270 |
| 7 live threads created before the worker exited, no lookup | 30 | 120/120 |
| 10 live threads created before the worker exited, no lookup | 29 to 30 | 119/120 |
| 7 live threads created before the worker exited, lookup of an unrelated file | 30 | 120/120 |
| 10 live threads created before the worker exited, lookup of an unrelated file | 29 to 30 | 119/120 |
| No cache worker | 0 | 0/270 |
| Copied executable | 0 | 0/270 |

The eviction boundary is exact: with the main thread's lookup plus seven
others newer than the stale record, the stale record is gone, matching the
capacity of eight per-inode origins measured earlier for APFS. Because the
evictors are created while the stale worker is still alive, none of them can
reuse its thread object, so this is eviction and not overwriting. Two live
holder threads protect the launch almost completely (the two-holder row),
consistent with the launched thread taking the most recently freed object. Dead dummy threads
only reduce the rate, so allocation is not strictly last-in-first-out.

The matched controls settle what the evictors do: seven or ten live threads
created before the worker exits that look up nothing, or an unrelated file,
leave 30 of 30 cache paths, while the same threads looking up the environment
alias leave 0. Eviction is driven by lookups of this inode, not by the
threads' existence.

Whether real retries pass because of eviction, because a thread that reuses
the stale identity overwrites the record with its own lookup, or because the
retry's thread simply does not reuse that identity is not settled by this
experiment; the retained-inode retry test below addresses it. A delay alone is
not an established fix.

## Filesystems

[image_probe.py](image_probe.py) runs the Conda-free reproducer on the host
volume and on 128 MB APFS and HFS+ disk images in the same job, 30 trials per
cell. Each run used a fresh runner VM with the same macOS build; from run 6 on,
the job mounted three fresh images of each type in alternating order. Cache
paths in the two exited-cache-worker cells combined, out of 60:

| Volume | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Run 6 | Run 7 | Run 8 | Run 9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| host-apfs | 57 | 60 | 58 | 49 | 58 | 58 | 59 | 59 | 60 |
| image-apfs | 57 | 54 | 52 | 57 | 60 |  |  |  |  |
| image-apfs-1 |  |  |  |  |  | 55 | 57 | 59 | 59 |
| image-apfs-2 |  |  |  |  |  | 45 | 60 | 58 | 57 |
| image-apfs-3 |  |  |  |  |  | 56 | 56 | 60 | 60 |
| image-hfs | 0 | 60 | 55 | 55 | 60 |  |  |  |  |
| image-hfs-1 |  |  |  |  |  | 59 | 53 | 57 | 60 |
| image-hfs-2 |  |  |  |  |  | 56 | 54 | 60 | 58 |
| image-hfs-3 |  |  |  |  |  | 53 | 58 | 33 | 59 |

All other cells were 0 in every run except three single launches, which the
generator lists under this table. HFS+ reproduces the exited-thread route in
every image-run but one: in run 1 it did not reproduce at all on that volume
while the APFS volumes in the same job did, and every HFS+ image since has
reproduced it. The all-or-nothing character of run 1 is unexplained and did
not recur. HFS+'s open-source origin cache keys records on
`current_thread()` pointers, keeps a bounded list per inode, and in
[`hfs_vfs_vget`](https://github.com/apple-oss-distributions/hfs/blob/d1bac2f062e6e9c0dfcce302d9aacb10173d0eea/core/hfs_vfsops.c#L3120)
uses a record for the calling thread without checking that the thread created
it; a recycled thread object would therefore inherit the record. The measured
HFS+ capacity of nine matches that source, which keeps eight file origins and
evicts only when the count exceeds eight. APFS's implementation is not public.
Its measured behavior is consistent with a structure like HFS's, with a
capacity of eight rather than nine, but nothing about its internals is
established.

Route two does not distinguish the filesystems.
[route2_probe.py](route2_probe.py) spawns the identity app suspended, performs
one lookup in the parent, and resumes it, 30 trials per cell on the same three
volumes, one value per run
([first run 41829581372](https://github.com/maresb/conda-lock/actions/runs/41829581372)):

| Lookup while the child is suspended | Host APFS | APFS image | HFS+ image |
|---|---:|---:|---:|
| None | 0, 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0, 0 | 0, 0, 0, 0, 1, 0 |
| `stat` of the cache alias | 30, 30, 28, 30, 29, 30 | 30, 30, 29, 29, 29, 29 | 30, 30, 30, 30, 30, 30 |
| `open` and `close` of the cache alias | 30, 30, 30, 30, 30, 30 | 30, 30, 30, 30, 30, 30 | 30, 30, 30, 30, 30, 30 |
| `open` of the cache alias, then `stat` of the environment alias | 2, 1, 2, 3, 0, 4 | 0, 2, 1, 0, 4, 2 | 0, 0, 0, 0, 0, 0 |
| Any, copied executable | 0 total over 6 runs | | |

A thread with no origin record of its own follows the most recent lookup on
every volume, which is what the HFS source says it does; the fallback test
below shows that this holds after the looking-up thread has exited, and that
a path build by a thread with a record of its own resets the fallback to
that thread's answer. The cell with a cache
`open` followed by an environment `stat` was nonzero in some APFS runs and zero
in every HFS+ run; that is an observed difference worth testing, not an
established one.

## Runner images and architectures

[reproduce_thread_exit.py](reproduce_thread_exit.py), 40 trials per cell,
cache paths in the two exited-cache-worker cells as the range over independent
runs; every other hardlink cell and every copy and clone cell was 0 in every
run, except a single launch in one run on `macos-15-intel`:

| Image | macOS | dyld | Arch | Runs | `spawn` | `exec` | Nonzero elsewhere |
|---|---|---|---|---:|---:|---:|---|
| `macos-15` | 15.8.2 | 1286.12 | arm64 | 8 | 38 to 40 | 36 to 40 | none |
| `macos-15-intel` | 15.7.9 | 1286.10 | x86_64 | 9 | 39 to 40 | 38 to 40 | [(41829764653, 'hardlink/env-alive/spawn', 1)] |
| `macos-26` | 26.6.2 | 1387 | arm64 | 6 | 34 to 39 | 34 to 40 | none |
| `macos-26-intel` | 26.6.1 | 1387 | x86_64 | 10 | 37 to 40 | 35 to 40 | [(41848719008, 'hardlink/cache-alive/spawn', 1)] |

The mechanism is not specific to macOS 26 or to Apple silicon.

## Clones and the cost of not hardlinking

A `clonefile(2)` copy has its own inode. In every clone trial the installed
file's inode differed from the cache file's, and over the four runner images
and all runs:

| Clone launches | In exited-cache-worker cells | Resolved to the cache |
|---:|---:|---:|
| 9600 | 2400 | 0 |

[link_cost_probe.py](link_cost_probe.py) times installing a 3,000-file tree
of 32 KiB files on the runner's APFS volume, median of five rounds per run,
fresh destination each round, as the range over runs; the per-file clone
row excludes two early runs that spawned one `cp` process per file:

| Method | Median seconds, range over runs | Runs | Runs faster than `os.link` |
|---|---:|---:|---:|
| `os.link` per file from Python | 0.85 to 1.41 | 9 |  |
| `clonefile(2)` per file from Python | 0.44 to 0.87 | 7 | 7 |
| `shutil.copyfile` per file from Python | 0.59 to 1.28 | 7 | 5 |
| `cp -Rc` (clone tree) | 0.42 to 0.76 | 9 | 9 |
| `cp -R` (copy tree) | 1.30 to 2.89 | 9 | 0 |

In this benchmark cloning was faster than hardlinking in every run. The
methods always ran in the same order, the files were uniform and freshly
written, and only one runner image and volume were measured, so this does
not establish installation cost in general. Micromamba's `--always-copy` copied
bytes rather than cloning for the executables the validation job below
measures.

## Installers

[installer_identity.py](installer_identity.py) installs the GDAL fixture with
micromamba 2.10.0 and with the current Miniconda's conda, and the current
conda-forge GDAL with the current pixi, then records whether `bin/gdalinfo`
shares an inode or storage with the package cache. Storage is compared extent
by extent with [log2phys.c](log2phys.c), which uses Apple's packed `struct
log2phys` directly; the first version of this probe decoded that structure at
the wrong offset and recorded only the high half of the first block's address,
so the storage columns of the earlier runs are not used. The three controls apply the same measurement to a hardlink, a `clonefile`
clone, and a byte copy of a fresh file. The corrected job was cancelled in
the queue four times (runs 41871897236, 41876823641, 41880415154, and
41885808126), each about fifteen minutes after queueing with the annotation
"The job was not acquired by Runner of type hosted even after multiple
attempts" and macOS arm64 capacity notices, and ran on the fifth dispatch
([run 41888487799](https://github.com/maresb/conda-lock/actions/runs/41888487799)):

| Installed file | Link count | Shares inode with cache or original | Storage shared with cache or original | Launches |
|---|---:|---|---|---:|
| micromamba 2.10.0 | 2 | yes | 69,424 of 69,424 bytes | 20/20 pass |
| conda (Miniconda latest) | 2 | yes | 69,424 of 69,424 bytes | 20/20 pass |
| pixi (rattler) | 1 | no | 277,200 of 277,200 bytes | 20/20 pass |
| Control: hardlink of a fresh 1 MiB file | 2 | yes | 1,048,576 of 1,048,576 bytes |  |
| Control: `cp -c` clone of it | 1 | no | 1,048,576 of 1,048,576 bytes |  |
| Control: byte copy of it | 1 | no | 0 of 1,048,576 bytes |  |

The pixi executable has its own inode and shares every byte of its storage
with the cache copy, exactly like the clone control, so rattler's reflink
produced a clone here. Twenty launches per installer all passed, which is consistent with the
roughly 4 percent first-launch rate of the natural runs; this job measures
identity, not rates. Rattler tries a reflink first and falls back to a
hardlink where reflinks are unsupported, so this executable on this APFS runner
is not exposed, while pixi installs are potentially exposed wherever that
fallback produces hardlinks. The pixi package differs (conda-forge GDAL 3.13.3
against defaults 3.6.2), which does not affect the identity check.

## Retrying on a retained inode

[retry_probe.py](retry_probe.py) creates the stale state with the reliable
in-process launcher, launches once, and then retries the same inode under one
condition, followed by a second retry with no explicit lookup
([run 41842075808](https://github.com/maresb/conda-lock/actions/runs/41842075808)):

| Retry condition | First launch chose cache | Retry chose cache, given a wrong first launch | Second retry chose cache |
|---|---:|---:|---:|
| `posix_spawn` with no explicit lookup, immediately | 24/30 | 0/24 | 0/24 |
| `posix_spawn` with no explicit lookup, after 2 s | 27/30 | 0/27 | 0/27 |
| Launcher looks up the environment alias, then spawns | 27/30 | 0/27 | 0/27 |
| Launcher looks up the environment alias, then execs | 26/30 | 0/26 | 0/26 |
| Python spawns directly | 23/30 | 0/23 | 0/23 |

A wrong-path launch does not leave the inode in a state that fails again:
every retry passed, with no delay and no explicit lookup. Note that any spawn
or exec of the environment alias is itself a path lookup by the launching
thread, so "no explicit lookup" is not "no lookup". A retry passes on its
own, and eviction by eight other threads is not required for it. The three
sections that follow test candidate explanations; none of them settles why.

## What a stale record does when read, refreshed, or held

[record_probe.py](record_probe.py) with [record_state.c](record_state.c) needs
no executable. The main thread opens the environment alias; a worker looks up
the cache alias and exits; the main thread then looks up the environment alias
again, so that a thread without an inherited record reads the environment path
and only a thread that inherited the worker's record can read the cache path.
Thread X then runs and exits, and thread Y reads the path by inode once. Each
thread is created after the previous one was joined, so each may reuse the
previous thread's identity. In the `read` cells X reads twice, with an optional
pause before X is created; in `refresh` it reads, looks up the environment
alias itself, and reads again; in `norestore` the main thread's restoring
lookup is omitted, which was the first design of this probe; `control` has no
worker. Forty trials per cell, fresh inode each, two runs
([first run 41876823641](https://github.com/maresb/conda-lock/actions/runs/41876823641)):

| Cell | Trials | X first read cache | X second read cache, given first cache | X second read env, given first cache | Y read cache, given X second read cache | Y read cache, given X second read env | Y read cache, given X first read env |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 80 |  |  |  |  |  |  |
| control | 80 | 0 |  |  |  | 0 | 0 |
| norestore | 80 | 48 | 48 | 0 | 48 | 16 | 16 |
| read | 80 | 64 | 64 | 0 | 64 | 12 | 12 |
| read/sleep1000ms | 80 | 0 |  |  |  | 0 | 0 |
| read/sleep200ms | 80 | 11 | 11 | 0 | 11 | 3 | 3 |
| refresh | 80 | 59 | 0 | 59 |  | 16 | 16 |

In the `hold` cells a holder thread is created right after the restoring
lookup, reads the path, sleeps with no filesystem activity, reads again, and
exits before X runs:

| Hold cell | Trials | Holder's first read cache | Second read cache, given first cache | Second read env, given first cache | X first read cache, given holder's first cache | X first read cache, given holder's first env |
|---|---:|---:|---:|---:|---:|---:|
| hold/sleep1000ms | 80 | 61 | 61 | 0 | 61 | 0 |
| hold/sleep5000ms | 80 | 66 | 66 | 0 | 66 | 0 |

The fallback test below shows that a path build by a thread with its own
record sets the fallback to that thread's answer. Nothing in this design
resets the fallback between a thread's reads, so a thread's first read of
the cache path installed the cache path as the fallback, and its second
read, the holder's read after its pause, and every read after that could
have come from the fallback rather than from a record. Two conclusions
survive that:

- **A lookup by the holder replaces the stale answer.** In `refresh`, after
  X read the cache path and looked up the environment alias itself, its
  second read returned the environment path every time, and Y then read the
  environment path in every one of those trials. Under either reading of
  the fallback, the stale answer was gone for X and for Y.
- **After the identity is freed, the cache answer disappears within a
  second.** With no holder, X read the cache path in a few trials after
  200 ms, and neither X nor Y did after one second, in both runs. A first read follows
  the main thread's restoring lookup, so these are records, not fallback
  answers.

Whether reading consumes the record and whether a held record survives a
pause are open after this run. The third design,
[record_state3.c](record_state3.c) with [record_probe3.py](record_probe3.py),
has the main thread look up the environment alias and build the path
itself before every read by a probe thread; it is dispatched as
[run 41889196235](https://github.com/maresb/conda-lock/actions/runs/41889196235)
and its results are pending.

In-process reuse is not deterministic: X's first read returned the cache
path in most trials but not all, and when X missed, Y sometimes received
the record instead. The `norestore` cell's lower count than the superseded
design's is explained by the fallback test: the main thread's `fsgetpath`
after the worker exits resets the fallback, and the superseded design had
no such call.

The first design of this probe lacked the restoring lookup, so a thread
without the worker's record read the cache path through the fallback, as
the fallback test shows, and nothing it measured distinguishes the two. Its
summaries remain in the evidence record under `record-probe`, printed by the
generator as a superseded table, and are not used here.

## Does the fallback follow an exited thread's lookup?

[fallback_probe.py](fallback_probe.py) with
[fallback_state.c](fallback_state.c) creates an idle reader thread before
the worker, so the reader cannot inherit the worker's identity, and then
varies whether the worker exits or stays alive after looking up the cache
alias and whether the main thread calls `fsgetpath` afterwards, as
`record_state` does. Nothing looks up the environment alias after the
worker. The reader then reads the path by inode, X reads twice, and Y reads
once. Two cells without a reader reproduce the superseded design's sequence
and the `norestore` sequence. Forty trials per cell, fresh inode each
([run 41885808126](https://github.com/maresb/conda-lock/actions/runs/41885808126)):

| Cell | Trials | Reader read cache | X first read cache | X first read cache, given reader cache | X first read cache, given reader env | Y read cache |
|---|---:|---:|---:|---:|---:|---:|
| No worker | 40 | 0 | 0 |  | 0 | 0 |
| No worker, main thread reads | 40 | 0 | 0 |  | 0 | 0 |
| Worker alive | 40 | 37 | 37 | 37 | 0 | 37 |
| Worker alive, main thread reads | 40 | 0 | 2 |  | 2 | 1 |
| Worker exited | 40 | 40 | 40 | 40 |  | 40 |
| Worker exited, main thread reads | 40 | 0 | 38 |  | 38 | 40 |
| No reader, worker exited (superseded design's sequence) | 40 |  | 40 |  |  | 40 |
| No reader, worker exited, main thread reads (`norestore`'s sequence) | 40 |  | 16 |  |  | 29 |

The reader, which cannot hold the worker's record, read the cache path in
every trial after the worker had exited and in nearly every trial while it
was alive, and the environment path in every trial after the main thread
had built the path. The fallback therefore follows the most recent lookup
whether or not the looking-up thread is still alive, and a path build by a
thread with its own record resets it to that thread's answer. The two
reader-less cells reproduce the superseded design's every-trial result and
the lower `norestore` count, which that reset explains. With the fallback
reset to the environment path, X's cache answers are inherited records: X
inherited in nearly every trial when the idle reader existed and in fewer
than half when it did not, so in-process inheritance also depends on what
other threads exist, which is not explained.

## Does a delay before the first launch help?

[delay_probe.py](delay_probe.py) models `micromamba create` then
`micromamba run` with a finished process that looks up the cache alias from
its main thread, a pause, then a launcher that looks up the environment
alias and spawns it. Twenty trials per cell, fresh inode each:

| Cell | Run 41846567784 | Run 41848913533 |
|---|---:|---:|
| Hardlink, 0 s | 11/20 | 9/20 |
| Hardlink, 0.2 s |  | 3/20 |
| Hardlink, 0.5 s |  | 0/20 |
| Hardlink, 1 s | 0/20 | 1/20 |
| Hardlink, 5 s | 0/20 | 0/20 |
| Hardlink, 20 s | 0/20 | 0/20 |
| Copy, 0 s | 0/20 | 0/20 |

A pause of half a second or more left at most one wrong-path launch in
twenty on these runners, and 200 ms left three. This contradicts the
expectation stated earlier in this document and supports the sleep proposed
in cmake-feedstock#230 as a mitigation on hosts like these. What changes
during the pause is not established: background load was not varied, so the
result shows neither that the effect is load-dependent nor that half a second
suffices elsewhere. The turnover test below shows that thread creation in
another process does not accelerate the loss of the stale answer over a
pause; whether the record expires after its thread exits is open.

## Thread turnover during a pause

[churn_probe.py](churn_probe.py) repeats the record probe's `read` cell with
a pause of 0, 0.2, or 1 s before X is created, in alternating blocks with
and without a separate process ([churn.c](churn.c)) that creates and joins
four threads at a time continuously. If turnover removes the stale answer,
the churning process should lower the counts; if time alone does, it should
not ([run 41885808126](https://github.com/maresb/conda-lock/actions/runs/41885808126)):

| Cell | Run 41885808126 |
|---|---:|
| Without a churning process, 0 s pause | 22/40 |
| Without a churning process, 0.2 s pause | 6/40 |
| Without a churning process, 1 s pause | 0/40 |
| With a churning process, 0 s pause | 25/40 |
| With a churning process, 0.2 s pause | 2/40 |
| With a churning process, 1 s pause | 1/40 |

The churning process did not lower the counts: with it running, X read the
cache path about as often at 0 s and at 0.2 s, and once at 1 s. The loss of
the stale answer over a pause is therefore not caused by thread turnover in
another process, and it tracks elapsed time. Whether the record is dropped
some time after its thread exits, or the freed identity is handed out
through a slower path than turnover on the same core, is not separated.
These are first reads after the main thread's restoring lookup and do not
depend on the fallback.

## Spawning again from the same process

[respawn_probe.py](respawn_probe.py) with [respawn.c](respawn.c) creates the
stale state once and then spawns the identity app four times from the same
long-lived process, so no intermediate process or thread exists between the
launches. Thirty trials per mode, fresh inode each, two runs:

| Cell | Run 41848913533 | Run 41851263227 |
|---|---:|---:|
| Hardlink, launch 1 | 28/30 | 27/30 |
| Hardlink, launch 2 | 2/30 | 2/30 |
| Hardlink, launch 3 | 0/30 | 1/30 |
| Hardlink, launch 4 | 0/30 | 0/30 |
| Copy, launch 1 | 0/30 | 0/30 |
| Copy, launch 4 | 0/30 | 0/30 |

In each of the 60 hardlink trials exactly one launch chose the cache path,
usually the first, and every launch after it chose the environment path.
Keeping the parent alive removes an intermediate launcher process from the
sequence; it does not remove background activity, and each spawn and dyld
start-up performs operations of its own, so this does not show that a
particular identity was handed out exactly once. The mechanism behind the
pattern, and so behind passing retries, is not resolved by these probes.
The contrast with the record probe, where a thread that had read the stale
path handed the identity to the next thread in every such trial, is the
observation to explain.

## Validating the CI workaround

The `workaround-validation` job runs the integration test's three `micromamba
create` commands with `--always-copy` on the committed lockfile fixtures, plus
the explicit lockfile without it, then records each `gdalinfo`'s identity,
launches it twenty times, and runs the test's own `micromamba run ... gdalinfo
--version` once. Storage is compared extent by extent as in the installers
section, with the same three controls
([run 41876823641](https://github.com/maresb/conda-lock/actions/runs/41876823641)):

| Installed file | Link count | Shares inode with cache or original | Storage shared with cache or original | Launches |
|---|---:|---|---|---:|
| `gdal-test-mm-lock`, unified lockfile, `--always-copy` | 1 | no | 0 of 69,424 bytes | 20/20 pass |
| `gdal-test-mm-explicit`, explicit lockfile, `--always-copy` | 1 | no | 0 of 69,424 bytes | 20/20 pass |
| `gdal-test-mm-env`, environment YAML, `--always-copy` | 1 | no | 0 of 69,424 bytes | 20/20 pass |
| `gdal-test-mm-hardlink`, explicit lockfile, default | 2 | yes | 69,424 of 69,424 bytes | 20/20 pass |
| Control: hardlink of a fresh 1 MiB file | 2 | yes | 1,048,576 of 1,048,576 bytes |  |
| Control: `cp -c` clone of it | 1 | no | 1,048,576 of 1,048,576 bytes |  |
| Control: byte copy of it | 1 | no | 0 of 1,048,576 bytes |  |

The copies have their own inodes and link count one, so the hardlink is
removed by construction, which is what the workaround needs, and the test's
own `micromamba run` command passed for each environment. These executables
share no storage with the cache, while the clone control shares all of it,
so for them `--always-copy` produced byte copies rather than clones; how
micromamba copies every other file was not measured. A copy costs disk
relative to a clone, and in the benchmark above also time. This job validates
compatibility and storage separation; the evidence that an unshared
executable prevents the failure is the copy and clone cells of the trigger
experiments above.

## Why this fits the original failure

[Three more original-sequence jobs](https://github.com/maresb/conda-lock/actions/runs/41803396689)
produced 3 first-launch failures in 72, without artificial workers or
requested indexing, all passing on retry. With the earlier fresh-install
experiment that is 4 of 144 first launches, each with the wrong cache
executable path and the original library signature. In those traces no
cache-path lookup appears between `execve` and the wrong `fsgetpath` result;
the last retained cache-executable access before each failure is micromamba's
own installation activity. In the original failing job the environment that
failed had been created 35 seconds earlier, but another environment's creation
had hardlinked the same cached `gdalinfo` 2 seconds earlier, from threads that
had since exited.

## Mechanism

Established by experiment:

- Inode-based `fsgetpath` on APFS honors a per-thread origin record when the
  calling thread has one and otherwise follows the most recent lookup or
  path build by any thread, alive or exited; a record survives its thread's
  exit; eight records are kept per inode.
- The stale answer is replaced when the thread holding the record looks up
  the environment alias, and disappears within a second after the identity
  is freed, which thread turnover in another process does not accelerate.
  Whether a read consumes the record and whether a held record expires are
  open until the third record probe runs.
- The launched process's first thread can inherit such a record from an
  exited thread of the same or another process, and keeping that thread alive
  or occupying the freed object with other live threads prevents it.
- A retry after a wrong-path launch passed in every tested condition, and
  repeated launches from one process chose the cache path at most once per
  trial; why is not established.
- Apple's published [dyld main-path code](https://github.com/apple-oss-distributions/dyld/blob/fd8d0c4d52320ebf64db34f3cb280310d905c5ae/dyld/DyldProcessConfig.cpp#L656)
  prefers that inode-based result over the kernel-supplied executable path,
  and the kernel supplies the inode in the `executable_file=` string
  ([kern_exec.c](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_exec.c#L6306)).

Inferred, not observed: that the record is keyed on the kernel thread object
and that the object is recycled. No kernel pointer or APFS data structure was
inspected. HFS+ reproduced the effect in every image-run but one, as its
documented semantics predict; the one run without it is unexplained.

## Consequences

- Copying or cloning the executable avoids the problem by construction; a
  clone costs no data copy on APFS. Copying only libraries does not help.
- A pause of half a second or more before the launch left at most one
  wrong-path launch in twenty on these hosted runners, and a retry after a
  wrong-path launch passed in every tested condition. Both are mitigations
  whose mechanism is not established, not fixes; thread turnover in another
  process does not accelerate the loss of the stale answer over a pause, and
  what removes it is not separated.
- Both installers and dyld could address it: installers by not hardlinking
  Mach-O executables on macOS (cloning keeps the space savings), dyld by using
  the kernel-supplied `executable_path` or a link ID, which the earlier runs
  showed always names the requested alias.

## Reproducing

```sh
python3 experiments/gdal-dyld/reproduce_thread_exit.py --output /tmp/dyld-thread-exit
python3 experiments/gdal-dyld/reproduce_cross_process.py --output /tmp/dyld-cross-process
```

Both need only Xcode Command Line Tools and the adjacent C sources, finish in
under a minute, and crash nothing.
