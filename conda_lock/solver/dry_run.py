"""Solver dryrun normalization.

Conda's ``--dry-run --json`` output is the protocol that conda-lock
consumes from conda/mamba/micromamba. This module owns translating
that output into a uniform shape with one ``FETCH`` per planned
package, regardless of whether the underlying solver returned
rich-LINK actions (mamba 2.x / micromamba), sparse-LINK actions
(conda, Python mamba 1.x), or already-complete FETCH actions.
"""

from typing import cast

from conda_lock.models.dry_run_install import FetchAction, LinkAction


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
    on disk.

    Synthesis is rejected unless the LINK has every field that the
    downstream code (``solve_conda``) reads from a FETCH. Critically we
    require ``depends`` to be present *and* a list, otherwise an absent
    or null value would silently erase a package's runtime dependencies.
    """
    for key in _FETCH_KEYS_FROM_LINK:
        if key not in link_action or link_action[key] is None:  # type: ignore[literal-required]
            return None
    if not isinstance(link_action["depends"], list):
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
