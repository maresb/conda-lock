# Exited-thread trigger: follow-up experiments, 2026-11-04

**A lookup of the package-cache alias by a thread that has since exited is
sufficient to make dyld resolve a hardlinked executable to the cache path.
The lookup can come from a separate, already-finished process. Keeping the
looking-up thread alive prevents it, and so do seven later lookups of the
environment alias by other live threads. The effect is present on macOS 15 and
26, on arm64 and x86_64, on APFS volumes, on APFS disk images, and on eight of nine HFS+ disk images
tested. Copied and cloned executables never resolve to the cache. After a
wrong-path launch, every retry of the same inode passed, with or without
further lookups or delay.**

All runs used GitHub-hosted runners in `maresb/conda-lock`. The earlier
[TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) records the spontaneous failures and
the suspended-start experiment. Run and artifact identifiers, host versions,
artifact digests, and every summary table in this document are collected in
[followup-evidence.json](followup-evidence.json), which covers six runs of
the follow-up workflow (41828207360, 41829030048, 41829581372, 41829764653,
41830505785, 41842075808) plus the lifecycle and standalone runs cited below.
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
Fresh inode per trial, 30 trials per cell, six independent runs; cache paths
chosen, as the range over runs:

| Finished process looked up cache from | Python launches directly | Launcher spawns | Launcher execs |
|---|---:|---:|---:|
| Nothing (control) | 0 | 0 | 0 |
| Its main thread | 0 to 5 | 21 to 25 | 14 to 28 |
| One exited worker | 19 to 29 | 3 to 8 | 3 to 10 |
| Four exited workers | 24 to 29 | 3 to 12 | 3 to 11 |
| Any, copied executable | 0/2160 total | | |

The rates swap between the direct and launcher columns depending on which
threads exited last. That is consistent with reuse of recently freed kernel
thread objects, with an intermediate process consuming the most recently freed
one before the launched thread is created, but neither the objects nor the
allocation order were observed. The `micromamba create` then `micromamba run`
sequence corresponds to the launcher columns.

## What happens between exit and launch

[scrub_probe.py](scrub_probe.py) with [scrub_exec.c](scrub_exec.c) keeps the
exited cache worker and varies what follows, 30 trials per cell on macOS 26.6.2,
six independent runs (the matched controls in the last run only); cache paths
out of 30 as the range over runs:

| Between the worker's exit and the launch | Range | Total |
|---|---:|---:|
| Nothing, `spawn` | 25 to 30 | 173/180 |
| Nothing, `exec` | 26 to 30 | 168/180 |
| 1 dummy threads created and joined | 17 to 28 | 140/180 |
| 2 dummy threads created and joined | 12 to 22 | 109/180 |
| 4 dummy threads created and joined | 15 to 19 | 102/180 |
| 8 dummy threads created and joined | 15 to 20 | 104/180 |
| 1 holder threads kept alive | 4 to 16 | 54/180 |
| 2 holder threads kept alive | 0 to 1 | 3/180 |
| 4 holder threads kept alive | 0 | 0/180 |
| 1 live threads that looked up the environment alias before the worker exited | 29 to 30 | 179/180 |
| 3 live threads that looked up the environment alias before the worker exited | 29 to 30 | 177/180 |
| 5 live threads that looked up the environment alias before the worker exited | 29 to 30 | 177/180 |
| 6 live threads that looked up the environment alias before the worker exited | 29 to 30 | 178/180 |
| 7 live threads that looked up the environment alias before the worker exited | 0 | 0/180 |
| 8 live threads that looked up the environment alias before the worker exited | 0 | 0/180 |
| 10 live threads that looked up the environment alias before the worker exited | 0 | 0/180 |
| 7 live threads created before the worker exited, no lookup | 30 | 30/30 |
| 10 live threads created before the worker exited, no lookup | 30 | 30/30 |
| 7 live threads created before the worker exited, lookup of an unrelated file | 30 | 30/30 |
| 10 live threads created before the worker exited, lookup of an unrelated file | 30 | 30/30 |
| No cache worker | 0 | 0/180 |
| Copied executable | 0 | 0/180 |

The eviction boundary is exact: with the main thread's lookup plus seven
others newer than the stale record, the stale record is gone, matching the
capacity of eight per-inode origins measured earlier for APFS. Because the
evictors are created while the stale worker is still alive, none of them can
reuse its thread object, so this is eviction and not overwriting. Two live
holder threads protect the launch almost completely (3 of 180 cache paths in
six runs), consistent with the
launched thread taking the most recently freed object. Dead dummy threads
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
cell. The job ran six times on six runner VMs with the same macOS build; in
run 6 it mounted three fresh images of each type in alternating order. Cache
paths in the two exited-cache-worker cells combined, out of 60:

| Volume | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Run 6 |
|---|---:|---:|---:|---:|---:|---:|
| host-apfs | 57 | 60 | 58 | 49 | 58 | 58 |
| image-apfs | 57 | 54 | 52 | 57 | 60 |  |
| image-apfs-1 |  |  |  |  |  | 55 |
| image-apfs-2 |  |  |  |  |  | 45 |
| image-apfs-3 |  |  |  |  |  | 56 |
| image-hfs | 0 | 60 | 55 | 55 | 60 |  |
| image-hfs-1 |  |  |  |  |  | 59 |
| image-hfs-2 |  |  |  |  |  | 56 |
| image-hfs-3 |  |  |  |  |  | 53 |

All other cells were 0 in every run, except one launch in a
cache-alive cell in run 1. HFS+ reproduces the exited-thread route on eight of
nine volumes; in run 1 it did not reproduce at all on that volume while the
APFS volumes in the same job did, and three fresh HFS+ images in run 6 all
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
| None | 0, 0, 0, 0 | 0, 0, 0, 0 | 0, 0, 0, 0 |
| `stat` of the cache alias | 30, 30, 28, 30 | 30, 30, 29, 29 | 30, 30, 30, 30 |
| `open` and `close` of the cache alias | 30, 30, 30, 30 | 30, 30, 30, 30 | 30, 30, 30, 30 |
| `open` of the cache alias, then `stat` of the environment alias | 2, 1, 2, 3 | 0, 2, 1, 0 | 0, 0, 0, 0 |
| Any, copied executable | 0 total over 4 runs | | |

A thread with no origin record of its own follows the most recent lookup on
every volume, which is what the HFS source says it does. The cell with a cache
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
| `macos-15` | 15.8.2 | 1286.12 | arm64 | 6 | 38 to 40 | 36 to 40 | none |
| `macos-15-intel` | 15.7.9 | 1286.10 | x86_64 | 6 | 39 to 40 | 38 to 40 | [(41829764653, 'hardlink/env-alive/spawn', 1)] |
| `macos-26` | 26.6.2 | 1387 | arm64 | 4 | 37 to 39 | 34 to 40 | none |
| `macos-26-intel` | 26.6.1 | 1387 | x86_64 | 6 | 37 to 40 | 35 to 40 | none |

The mechanism is not specific to macOS 26 or to Apple silicon.

## Clones and the cost of not hardlinking

A `clonefile(2)` copy has its own inode. In every clone trial the installed
file's inode differed from the cache file's, and 0 of 4,800 clone launches
across the four images and four runs resolved to the cache, 1,200 of them in
the exited-cache-worker cells.

[link_cost_probe.py](link_cost_probe.py) times installing a 3,000-file tree
of 32 KiB files on the runner's APFS volume, median of five rounds, fresh
destination each round:

| Method | Seconds |
|---|---:|
| `os.link` per file from Python | 0.86 |
| `clonefile(2)` per file from Python | 0.47 |
| `shutil.copyfile` per file from Python | 0.93 |
| `cp -Rc` (clone tree) | 0.44 |
| `cp -R` (copy tree) | 1.80 |

A second run gave medians within 0.15 s of these; two earlier runs spawned
one `cp` process per file instead and are not comparable. In this benchmark
cloning was faster than hardlinking. The methods always ran in the same order,
the files were uniform and freshly written, and only one runner and volume
were measured, so this does not establish installation cost in general, and
whether micromamba's copy mode clones or copies bytes was not checked.

## Installers

[installer_identity.py](installer_identity.py) installs the GDAL fixture with
micromamba 2.10.0 and with the current Miniconda's conda, and the current
conda-forge GDAL with the current pixi, then records whether `bin/gdalinfo`
shares an inode with the package cache
([run 41830505785](https://github.com/maresb/conda-lock/actions/runs/41830505785)):

| Installer | Installed `gdalinfo` | Package cache copy | Exposed |
|---|---|---|---|
| micromamba 2.10.0 | link count 2, same inode as the cache | same inode | yes |
| conda (Miniconda latest) | link count 2, same inode as the cache | same inode, in `~/conda_pkgs_dir` | yes |
| pixi (rattler) | link count 1, own inode, same hash | separate inode | no |

Twenty launches per installer all passed, which is consistent with the
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
thread, so "no explicit lookup" is not "no lookup". Which of these explains
the result is not established: the launching thread may reuse the stale
identity and refresh its record through that lookup, the wrong launch itself
may refresh or consume the record, or the identity may simply not be reused
twice. What the data do settle is practical: a retry passes on its own, and
eviction by eight other threads is not required for it.

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
  calling thread has one and otherwise follows the most recent lookup; a
  record survives its thread's exit; eight records are kept per inode.
- The launched process's first thread can inherit such a record from an
  exited thread of the same or another process, and keeping that thread alive
  or occupying the freed object with other live threads prevents it.
- Apple's published [dyld main-path code](https://github.com/apple-oss-distributions/dyld/blob/fd8d0c4d52320ebf64db34f3cb280310d905c5ae/dyld/DyldProcessConfig.cpp#L656)
  prefers that inode-based result over the kernel-supplied executable path,
  and the kernel supplies the inode in the `executable_file=` string
  ([kern_exec.c](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_exec.c#L6306)).

Inferred, not observed: that the record is keyed on the kernel thread object
and that the object is recycled. No kernel pointer or APFS data structure was
inspected. HFS+ reproduced the effect on eight of nine volumes, as its
documented semantics predict; the one volume without it is unexplained.

## Consequences

- Copying or cloning the executable avoids the problem by construction; a
  clone costs no data copy on APFS. Copying only libraries does not help.
- A fixed delay after installation is not an established fix; the stale
  record was never observed to expire on its own. A retry after a wrong-path
  launch passed in every tested condition.
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
