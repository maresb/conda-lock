# Exited-thread trigger: follow-up experiments, 2026-11-04

**A lookup of the package-cache alias by a thread that has since exited is
sufficient to make dyld resolve a hardlinked executable to the cache path.
The lookup can come from a separate, already-finished process. Keeping the
looking-up thread alive prevents it, and so do seven later lookups of the
environment alias by other live threads. The effect is present on macOS 15 and
26, on arm64 and x86_64, on APFS volumes, on APFS disk images, and, in four of five runs, on an HFS+
disk image. Copied and cloned executables never resolve to the cache.**

All runs used GitHub-hosted runners in `maresb/conda-lock`. The earlier
[TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) records the spontaneous failures and
the suspended-start experiment. Run and artifact identifiers, host versions,
artifact digests, and every summary table in this document are collected in
[followup-evidence.json](followup-evidence.json), which covers five runs of
the follow-up workflow (41828207360, 41829030048, 41829581372, 41829764653,
41830505785) plus the lifecycle and standalone runs cited below. Each summary
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
Fresh inode per trial, 30 trials per cell, five independent runs; cache paths
chosen, as the range over runs:

| Finished process looked up cache from | Python launches directly | Launcher spawns | Launcher execs |
|---|---:|---:|---:|
| Nothing (control) | 0/30 | 0/30 | 0/30 |
| Its main thread | 0 to 5 | 21 to 25 | 19 to 27 |
| One exited worker | 19 to 24 | 6 to 8 | 5 to 6 |
| Four exited workers | 24 to 27 | 3 to 12 | 3 to 11 |
| Any, copied executable | 0/90 | 0/90 | 0/90 |

The rates swap between the direct and launcher columns depending on which
threads exited last, which is what reuse of the most recently freed kernel
thread objects predicts: an intermediate process consumes the top of the free
list before the launched thread is created. The `micromamba create` then
`micromamba run` sequence corresponds to the launcher columns.

## What happens between exit and launch

[scrub_probe.py](scrub_probe.py) with [scrub_exec.c](scrub_exec.c) keeps the
exited cache worker and varies what follows, 30 trials per cell on macOS 26.6.2,
five independent runs; cache paths out of 30 as the range over runs:

| Between the worker's exit and the launch | Cache paths |
|---|---:|
| Nothing (`spawn` / `exec`) | 25 to 30 / 26 to 29 |
| 1, 2, 4, 8 dummy threads created and joined, no filesystem activity | 12 to 25 |
| 1 holder thread created and kept alive, no filesystem activity | 4 to 16 |
| 2 or 4 holder threads kept alive | 0 to 1 / 0 |
| 1, 3, 5, 6 live threads that looked up the environment alias before the worker exited | 29 to 30 |
| 7, 8, 10 such threads | 0 in every run |
| No cache worker; or copied executable | 0 / 0 |

The eviction boundary is exact: with the main thread's lookup plus seven
others newer than the stale record, the stale record is gone, matching the
capacity of eight per-inode origins measured earlier for APFS. Because the
evictors are created while the stale worker is still alive, none of them can
reuse its thread object, so this is eviction and not overwriting. Two live
holder threads protect the launch almost completely, consistent with the
launched thread taking the most recently freed object. Dead dummy threads
only reduce the rate, so allocation is not strictly last-in-first-out.

This explains why retries pass: every launch adds lookups from new threads,
and after about eight the stale record is evicted. It also explains why a
delay alone is unreliable: nothing evicts the record until other threads look
the inode up.

## Filesystems

[image_probe.py](image_probe.py) runs the Conda-free reproducer on the host
volume and on 128 MB APFS and HFS+ disk images in the same job, 30 trials per
cell. The job ran five times on five runner VMs with the same macOS build.
Cache paths in the two exited-cache-worker cells combined, out of 60:

| Volume | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|---|---:|---:|---:|---:|---:|
| Host APFS | 57 | 60 | 58 | 49 | 58 |
| APFS image | 57 | 54 | 52 | 57 | 60 |
| HFS+ image | 0 | 60 | 55 | 55 | 60 |

All other cells were 0 in every run, except one launch in a
cache-alive cell in run 1. HFS+ reproduces the exited-thread route in four of
five runs; in run 1 it did not reproduce at all on that volume while the APFS
volumes in the same job did. The all-or-nothing character of that run is
unexplained. HFS+'s open-source origin cache keys records on
`current_thread()` pointers, keeps a bounded list per inode, and in
[`hfs_vfs_vget`](https://github.com/apple-oss-distributions/hfs/blob/d1bac2f062e6e9c0dfcce302d9aacb10173d0eea/core/hfs_vfsops.c#L3120)
uses a record for the calling thread without checking that the thread created
it; a recycled thread object therefore inherits the record. The APFS
implementation is not public, but it behaves the same way in every measured
respect, including the capacity of eight.

Route two does not distinguish the filesystems.
[route2_probe.py](route2_probe.py) spawns the identity app suspended, performs
one lookup in the parent, and resumes it, 30 trials per cell on the same three
volumes; identical in all three runs
([first run 41829581372](https://github.com/maresb/conda-lock/actions/runs/41829581372)):

| Lookup while the child is suspended | Host APFS | APFS image | HFS+ image |
|---|---:|---:|---:|
| None | 0/30 | 0/30 | 0/30 |
| `stat` of the cache alias | 30/30 | 30/30 | 30/30 |
| `open` and `close` of the cache alias | 30/30 | 30/30 | 30/30 |
| `open` of the cache alias, then `stat` of the environment alias | 2/30 | 0/30 | 0/30 |
| Any, copied executable | 0/120 | 0/120 | 0/120 |

A thread with no origin record of its own follows the most recent lookup on
every volume, which is what the HFS source says it does. HFS+ differs from APFS
only in that the launched thread never inherits an exited thread's record.

## Runner images and architectures

[reproduce_thread_exit.py](reproduce_thread_exit.py), 40 trials per cell,
cache paths in the two exited-cache-worker cells as the range over independent
runs; every other hardlink cell and every copy and clone cell was 0 in every
run, except a single launch in one run on `macos-15-intel`:

| Image | macOS | dyld | Arch | Runs | `spawn` | `exec` |
|---|---|---|---|---:|---:|---:|
| `macos-15` | 15.8.2 | 1286.12 | arm64 | 5 | 38 to 40 | 36 to 40 |
| `macos-15-intel` | 15.7.9 | 1286.10 | x86_64 | 5 | 39 to 40 | 38 to 40 |
| `macos-26` | 26.6.2 | 1387 | arm64 | 3 | 39 | 34 to 40 |
| `macos-26-intel` | 26.6.1 | 1387 | x86_64 | 5 | 37 to 39 | 35 to 39 |

The mechanism is not specific to macOS 26 or to Apple silicon.

## Clones and the cost of not hardlinking

A `clonefile(2)` copy has its own inode. In every clone trial the installed
file's inode differed from the cache file's, and 0 of 4,800 clone launches
across the four images and four runs resolved to the cache.

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

A second run gave medians within 0.15 s of these. Cloning was not slower
than hardlinking on this volume; it was faster. The
source files were freshly written and cached in memory, which flatters copying
more than cloning. The objection that avoiding hardlinks costs installation
speed does not hold for clones on APFS.

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
identity, not rates. Rattler's separate inode is a clone or copy, which is
why pixi users do not see the failure.

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
inspected, and HFS+ behaves differently despite similar documented semantics.

## Consequences

- Copying or cloning the executable avoids the problem by construction; a
  clone costs no data copy on APFS. Copying only libraries does not help.
- A fixed delay after installation is not a fix. The stale record persists
  until roughly eight other threads look the inode up.
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
