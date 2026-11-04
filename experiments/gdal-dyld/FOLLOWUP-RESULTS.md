# Exited-thread trigger: follow-up experiments, 2026-11-04

**A lookup of the package-cache alias by a thread that has since exited is
sufficient to make dyld resolve a hardlinked executable to the cache path.
The lookup can come from a separate, already-finished process. Keeping the
looking-up thread alive prevents it, and so do seven later lookups of the
environment alias by other live threads. The effect is present on macOS 15 and
26, on arm64 and x86_64, on APFS volumes, on APFS disk images, and on eight of nine HFS+ disk images
tested. Copied and cloned executables never resolve to the cache. After a
wrong-path launch, every retry of the same inode passed, and a pause of half
a second before the first launch avoided it on the hosted runner; both depend
on the stale thread identity reaching a launched process at most once.**

All runs used GitHub-hosted runners in `maresb/conda-lock`. The earlier
[TRIGGER-RESULTS.md](TRIGGER-RESULTS.md) records the spontaneous failures and
the suspended-start experiment. Run and artifact identifiers, host versions,
artifact digests, and every summary table in this document are collected in
[followup-evidence.json](followup-evidence.json), which covers every run of
the follow-up workflow, including one I cancelled after its queued jobs
duplicated the previous run, plus the lifecycle and standalone runs cited
below.
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
exited cache worker and varies what follows, 30 trials per cell on macOS 26.6.2,
six independent runs (the matched controls in the last run only); cache paths
out of 30 as the range over runs:

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
| None | 0, 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0, 0 | 0, 0, 0, 0, 1, 0 |
| `stat` of the cache alias | 30, 30, 28, 30, 29, 30 | 30, 30, 29, 29, 29, 29 | 30, 30, 30, 30, 30, 30 |
| `open` and `close` of the cache alias | 30, 30, 30, 30, 30, 30 | 30, 30, 30, 30, 30, 30 | 30, 30, 30, 30, 30, 30 |
| `open` of the cache alias, then `stat` of the environment alias | 2, 1, 2, 3, 0, 4 | 0, 2, 1, 0, 4, 2 | 0, 0, 0, 0, 0, 0 |
| Any, copied executable | 0 total over 6 runs | | |

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
| `macos-15` | 15.8.2 | 1286.12 | arm64 | 8 | 38 to 40 | 36 to 40 | none |
| `macos-15-intel` | 15.7.9 | 1286.10 | x86_64 | 9 | 39 to 40 | 38 to 40 | [(41829764653, 'hardlink/env-alive/spawn', 1)] |
| `macos-26` | 26.6.2 | 1387 | arm64 | 6 | 34 to 39 | 34 to 40 | none |
| `macos-26-intel` | 26.6.1 | 1387 | x86_64 | 10 | 37 to 40 | 35 to 40 | [(41848719008, 'hardlink/cache-alive/spawn', 1)] |

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
were measured, so this does not establish installation cost in general.
Micromamba's `--always-copy` copies bytes rather than cloning, as the
validation job below shows.

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
thread, so "no explicit lookup" is not "no lookup". The three sections that
follow test the candidate explanations: the record is not consumed by being
read, a same-identity lookup of the right alias refreshes it only sometimes,
and repeated spawns from one process show the identity reaching a launched
process only once. A retry passes on its own, and eviction by eight other
threads is not required for it.

## Does reading a stale record consume it?

[record_probe.py](record_probe.py) with [record_state.c](record_state.c)
needs no executable. The main thread opens the environment alias; a worker
looks up the cache alias and exits; thread X runs and exits; thread Y reads
the path by inode. X and Y are each created after the previous thread was
joined, so each may reuse the previous thread's identity. Forty trials per
mode, fresh inode each ([run 41843069281](https://github.com/maresb/conda-lock/actions/runs/41846567784)):

| Mode | Trials | X read cache | Y read cache | Y cache given X cache | Y env given X cache |
|---|---:|---:|---:|---:|---:|
| baseline | 160 | 0 | 160 | 0 | 0 |
| control | 160 | 0 | 0 | 0 | 0 |
| hold/sleep1000ms | 40 | 11 | 14 | 10 | 1 |
| hold/sleep5000ms | 40 | 3 | 4 | 3 | 0 |
| read | 160 | 160 | 160 | 160 | 0 |
| read/sleep1000ms | 80 | 2 | 2 | 2 | 0 |
| read/sleep200ms | 80 | 65 | 66 | 65 | 0 |
| refresh | 160 | 160 | 90 | 90 | 70 |

With no worker, X and Y both read the environment path. With a worker, Y
read the cache path in every trial whether or not X had read it first,
so identity reuse was deterministic in-process and **reading a record does
not consume or refresh it**. In the refresh mode, after X read the cache path
and then looked up the environment alias itself, Y still read the cache path
in about six of ten trials across runs. On HFS that lookup would update X's
record in place; on APFS it did so only sometimes, which is unexplained. With
a pause before X is created, X still received the stale identity after 200 ms
in four of five trials but after one second in only 2 of 80. The hold cells, in which
a live thread keeps the freed identity through the pause and then returns it,
separate record expiry from the identity being taken by another thread
during the pause. They answer only in part. With the identity held for one
second and then released, X read the cache path in 11 of 40 trials, and after
five seconds in 3 of 40, so the record survived those pauses in those trials
and there is no deterministic expiry on that scale. But a held identity was
not reliably handed back to X either, so the remaining trials cannot be
attributed to expiry rather than to allocation. The delay effect is therefore
best described as the stale identity becoming unlikely to reach the launched
thread within about half a second on a busy machine, not as the record
expiring.

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

A pause of half a second or more removed nearly every wrong-path launch on
this runner, and 200 ms removed most. This contradicts the expectation stated
earlier in this document and supports the sleep proposed in
cmake-feedstock#230 as a mitigation on busy machines. What changes during the
pause is which kernel object the launched thread receives, since a hosted
runner creates and destroys threads constantly in the background; the hold
cells above test whether the record itself also expires. Either way the
effect depends on background activity, and a quiet machine may behave
differently.

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
usually the first, and no later launch from the same process did, even
though nothing in between could have taken the freed object. Together with the previous sections this
settles why retries pass: not because the record is consumed or refreshed,
which it is not, but because a spawned process's thread is handed the stale
identity at most once in sequence. Why the kernel does not hand it out again
is not observable from user space; a process exit frees its thread
differently from an in-process join, which reuses the identity every time.

## Validating the CI workaround

The `workaround-validation` job runs the integration test's three
`micromamba create` commands with `--always-copy` on the committed lockfile
fixtures, plus the explicit lockfile without it, then records each
`gdalinfo`'s identity, launches it twenty times, and runs the test's own
`micromamba run ... gdalinfo --version` once:

| Environment | Link count | Shares inode with cache | Shares first physical block with cache | Launches |
|---|---:|---|---|---:|
| `gdal-test-mm-lock`, unified lockfile, `--always-copy` | 1 | no | no | 20/20 pass |
| `gdal-test-mm-explicit`, explicit lockfile, `--always-copy` | 1 | no | no | 20/20 pass |
| `gdal-test-mm-env`, environment YAML, `--always-copy` | 1 | no | no | 20/20 pass |
| `gdal-test-mm-hardlink`, explicit lockfile, default | 2 | yes | yes | 20/20 pass |

`--always-copy` produces a byte copy, not a clone: the copies share no
storage with the cache. That costs disk and time relative to cloning but
removes the hardlink by construction, which is what the workaround needs.

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
- A record is not consumed by being read, and a launched process receives a
  given stale identity at most once in sequence, so retries pass.
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
- The stale record was never observed to expire on its own, yet a one-second
  pause before the launch removed every wrong-path launch on the hosted
  runner, and a retry after a wrong-path launch passed in every tested
  condition. Both are mitigations that depend on other threads taking the
  freed identity, not fixes.
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
