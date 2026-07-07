"""Solver dryrun normalization.

Conda's ``--dry-run --json`` output is the protocol that conda-lock
consumes from conda/mamba/micromamba. This module owns translating
that output into a uniform shape with one ``FETCH`` per planned
package, regardless of whether the underlying solver returned
rich-LINK actions (mamba 2.x / micromamba), sparse-LINK actions
(conda, Python mamba 1.x), or already-complete FETCH actions.

This module hosts two user-facing warnings that are policy, not
cache I/O: the degraded-disk-fallback breadcrumb that
``reconstruct_fetch_actions_in_place`` emits when the rich-LINK fast path
is unavailable, and ``warn_on_pkgs_dirs_leak`` which surfaces a
``CONDA_PKGS_DIRS`` leak from the user's condarc. Both belong here
because both are the orchestration view of "the dryrun pipeline
hit a degraded path"; the cache layer in
``conda_lock.solver.repodata_cache`` only ever reports facts.
"""

import logging
import pathlib

from typing import cast

from conda_lock.invoke_conda import PathLike, conda_pkgs_dir, get_pkgs_dirs
from conda_lock.models.dry_run_install import DryRunInstall, FetchAction, LinkAction
from conda_lock.solver.repodata_cache import (
    get_repodata_record,
    is_mamba_2_1_to_2_5_stub_record,
)


logger = logging.getLogger(__name__)


def warn_on_pkgs_dirs_leak(pkgs_dirs: list[pathlib.Path]) -> None:
    """Detect extra pkgs_dirs leaking in from the user's ``.condarc``.

    conda-lock sets ``CONDA_PKGS_DIRS`` to an isolated temp directory
    in ``conda_env_override`` so the solver doesn't see whatever is
    in the user's global cache. In practice, several mamba/conda
    releases have *merged* the env-var with the condarc value rather
    than replacing it, leaking corrupt or stale entries from the
    user's cache into the solver's view (the third step in the
    conda/conda-lock#896 chain). Warn so this is at least visible.
    """
    expected = pathlib.Path(conda_pkgs_dir()).resolve()
    extras = [p for p in pkgs_dirs if p.resolve() != expected]
    if extras:
        logger.warning(
            "Extra pkgs_dirs leaked from user config: %s. conda-lock asked "
            "the solver to use only its isolated cache at %s, but the "
            "solver also reported %s. Stale or corrupt entries (notably "
            "from mamba 2.1.1-2.5 -- see conda/conda-lock#896) in the "
            "leaked directories may produce a broken lockfile.",
            extras,
            expected,
            extras,
        )


_FETCH_KEYS_FROM_LINK: tuple[str, ...] = (
    "channel",
    "depends",
    "fn",
    "md5",
    "name",
    "subdir",
    "timestamp",
    "url",
    "version",
)


def link_action_as_fetch(link_action: LinkAction) -> FetchAction | None:
    """Reuse a LINK action's metadata as a FETCH action when complete.

    Mamba-family solvers return LINK entries that already include every
    repodata field we need (``url``, ``fn``, ``md5``, ``sha256``,
    ``depends``, ``constrains``, ...) -- captured and verified for
    micromamba 1.5.12 through 2.8.1; conda and the Python ``mamba``
    1.x CLI emit sparse conda-meta LINKs instead. When the fields are
    all present we don't need to crack open ``repodata_record.json``
    on disk -- doubly useful given that mamba 2.6.0 reorganized the
    cache hierarchically by channel/subdir
    (see https://github.com/mamba-org/mamba/pull/4163), invalidating the
    flat-path lookup that ``get_repodata_record`` used to do.

    Synthesis is rejected unless the LINK has every field that the
    downstream code (``solve_conda``) reads from a FETCH. Critically we
    require ``depends`` to be present *and* a list, otherwise an absent
    or null value would silently erase a package's runtime dependencies.

    We also reject the fast path when the LINK metadata itself carries
    the mamba 2.1.1-2.5 corruption signature (``timestamp == 0`` plus
    empty ``license``, with empty ``depends`` or missing ``sha256``).
    In every dryrun we have captured, rich-LINK values come from
    channel repodata at solve time and are clean even when the local
    cache record is corrupt -- but that is an external invariant, not
    something this code can rely on. A solver flow that sources LINK
    values from cache records (offline operation, explicit/local
    sources) would let the corrupt fields ride straight into a FETCH,
    bypassing the cache-side heal completely. Routing such LINKs to
    disk fallback gives them a chance to be healed via
    ``info/index.json``.
    """
    for key in _FETCH_KEYS_FROM_LINK:
        if key not in link_action or link_action[key] is None:  # type: ignore[literal-required]
            return None
    if not isinstance(link_action["depends"], list):
        return None
    if is_mamba_2_1_to_2_5_stub_record(cast(dict, link_action)):
        return None
    fetch = cast(
        FetchAction,
        {key: link_action[key] for key in _FETCH_KEYS_FROM_LINK},  # type: ignore[literal-required]
    )
    # ``sha256`` and ``constrains`` are deliberately NOT in
    # ``_FETCH_KEYS_FROM_LINK``: both are optional in real repodata
    # (older .tar.bz2-era packages lack ``sha256``; most packages
    # declare no ``constrains``), so requiring them here would force
    # the disk fallback for packages whose cached record lacks them
    # just the same. ``sha256`` is copied through as-is because its
    # consumer (``HashModel.sha256`` via ``solve_conda``) is Optional;
    # ``constrains`` is normalized to ``[]`` to satisfy the
    # ``FetchAction`` schema -- conda-lock does not consume it today.
    fetch["sha256"] = link_action.get("sha256")
    constrains = link_action.get("constrains")
    fetch["constrains"] = constrains if isinstance(constrains, list) else []
    return fetch


def reconstruct_fetch_actions_in_place(
    conda: PathLike, platform: str, dry_run_install: DryRunInstall
) -> None:
    """Normalize a conda/mamba dryrun so every planned package has a FETCH.

    Conda may choose to link a previously downloaded distribution from
    ``pkgs_dirs`` rather than downloading a fresh one, in which case
    its dryrun returns only a LINK action, which for conda and the
    Python ``mamba`` 1.x CLI lacks the ``url`` / ``md5`` / ``sha256``
    / ``depends`` fields the package plan needs.
    For each LINK without a matching FETCH, this function either
    synthesizes one from the LINK metadata (mamba-family fast path)
    or reads ``repodata_record.json`` from the cache.

    **Mutates ``dry_run_install`` in place and returns ``None``.**
    The input's ``actions["FETCH"]`` list is extended (and
    ``actions["LINK"]`` / ``actions["FETCH"]`` keys created if
    absent). The ``_in_place`` suffix and the ``None`` return follow
    the ``list.sort`` convention: mutation is the entire point, and
    returning the mutated object would let a caller mistake this for
    a pure function and keep using the (also mutated) input. If you
    need the original dryrun pristine, deep-copy before calling.
    """
    if "LINK" not in dry_run_install["actions"]:
        dry_run_install["actions"]["LINK"] = []
    if "FETCH" not in dry_run_install["actions"]:
        dry_run_install["actions"]["FETCH"] = []

    link_actions = {p["name"]: p for p in dry_run_install["actions"]["LINK"]}
    fetch_actions = {p["name"]: p for p in dry_run_install["actions"]["FETCH"]}
    link_only_names = set(link_actions.keys()).difference(fetch_actions.keys())

    # Mamba-family solvers put the full repodata into LINK actions, so we
    # can often synthesize FETCH without going to disk. Resolve those first
    # and only query the (potentially expensive) ``pkgs_dirs`` listing if
    # anything is left over.
    deferred: list[tuple[str, LinkAction]] = []
    for link_pkg_name in link_only_names:
        link_action = link_actions[link_pkg_name]
        from_link = link_action_as_fetch(link_action)
        if from_link is not None:
            dry_run_install["actions"]["FETCH"].append(from_link)
        else:
            deferred.append((link_pkg_name, link_action))

    if deferred:
        # Visibility for the cache-dependent path. Mamba-family solvers
        # emit full repodata in LINK, so with them disk fallback is only
        # reached when a LINK was rejected (missing fields or the mamba
        # 2.1.1-2.5 corruption signature). With conda and the Python
        # mamba 1.x CLI, sparse LINKs make this the normal path. Either
        # way the cache may contain stale or corrupt records; we leave a
        # breadcrumb so a later silent-data bug isn't an archaeology
        # project. See conda/conda-lock#896.
        logger.warning(
            "Reconstructing FETCH actions from the package cache for "
            "%d package(s) on %s: %s. This path is normal for conda and "
            "the Python mamba 1.x CLI, whose dryrun LINK actions don't "
            "carry full repodata. With mamba 2.x/micromamba it is only "
            "reached when a LINK action was rejected as incomplete or "
            "as carrying the mamba 2.1.1-2.5 corruption signature -- "
            "in that case check the package cache for corrupt entries "
            "(see conda/conda-lock#896).",
            len(deferred),
            platform,
            sorted(name for name, _ in deferred),
        )
        pkgs_dirs = get_pkgs_dirs(conda=conda, platform=platform)
        warn_on_pkgs_dirs_leak(pkgs_dirs)
    else:
        pkgs_dirs = []

    for _link_pkg_name, link_action in deferred:
        if "dist_name" in link_action:
            dist_name = link_action["dist_name"]
        elif "fn" in link_action:
            dist_name = str(link_action["fn"])
            if dist_name.endswith(".tar.bz2"):
                dist_name = dist_name[:-8]
            elif dist_name.endswith(".conda"):
                dist_name = dist_name[:-6]
            else:
                raise ValueError(f"Unknown filename format: {dist_name}")
        else:
            raise ValueError(f"Unable to extract the dist_name from {link_action}.")
        lookup = get_repodata_record(pkgs_dirs, dist_name, link_action)
        # Translate cache-layer outcomes to user-facing warnings.
        # The cache layer is silent at WARNING level; this is where
        # operator-facing remediation text lives.
        if lookup.outcome == "healed":
            logger.warning(
                "Healed corrupt repodata_record.json at %s using "
                "info/index.json (mamba/micromamba 2.1.1-2.5 "
                "corruption signature, see conda/conda-lock#896 / "
                "mamba-org/mamba#4110). Run `mamba clean -a` and "
                "re-create your env on mamba 2.6.0+ to remove "
                "the corrupt cache permanently.",
                lookup.healed_from,
            )
        elif lookup.outcome == "unhealable_corrupt":
            logger.warning(
                "Cache record for %s carries the mamba 2.1.1-2.5 "
                "corruption signature and the sibling info/index.json "
                "is unavailable, so the record cannot be healed. "
                "Reason: %s. Regenerate from sources on a "
                "known-clean cache (`mamba clean -a` then "
                "`conda-lock lock -f <your sources> ...`) -- see "
                "conda/conda-lock#896 / mamba-org/mamba#4110.",
                dist_name,
                lookup.reason,
            )
        elif lookup.outcome == "not_found":
            logger.warning(
                "Failed to find repodata_record.json for %s. "
                "Giving up. Last reason: %s",
                dist_name,
                lookup.reason,
            )
        if lookup.record is None:
            raise FileNotFoundError(
                f"Distribution '{dist_name}' not found in pkgs_dirs {pkgs_dirs}"
            )
        dry_run_install["actions"]["FETCH"].append(lookup.record)
