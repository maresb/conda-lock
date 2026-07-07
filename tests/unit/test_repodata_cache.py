"""Unit tests for ``conda_lock.solver.repodata_cache``.

Cache-side concerns: URL normalization (libmamba parity),
hierarchical and legacy candidate-path derivation, identity checks
between cache records and LINK actions, mamba 2.1.1-2.5 stub-record
detection, and ``info/index.json``-based healing of those stubs.

The dict literals model real mamba/conda JSON output, which is
dynamically typed at the boundary -- pretending they were TypedDicts
at every call site would be a wall of casts without catching real
bugs. The relevant arg-type checks are disabled file-wide.
"""

# mypy: disable-error-code="arg-type,comparison-overlap"

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from conda_lock.solver.repodata_cache import (
    candidate_record_paths,
    get_repodata_record,
    hierarchical_cache_subpath,
    libmamba_strip_url_secrets,
    normalize_url_for_compare,
    record_matches_link,
)
from tests.support.fixtures import MAMBA_26_LINK_ACTION as _MAMBA_26_LINK_ACTION


def _matched(record: dict, link: dict) -> bool:
    matched, _reason = record_matches_link(record, link)
    return matched


def _write_record(path: Path, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_libmamba_strip_url_secrets_handles_no_scheme_credentials():
    """libmamba removes ``user:pass@`` and ``/t/<token>`` even on URLs
    without a scheme (see ``test_cpp.cpp`` ``URLs without scheme``)."""
    assert (
        libmamba_strip_url_secrets("root:secretpassword@myweb.com/test.repo")
        == "myweb.com/test.repo"
    )
    assert (
        libmamba_strip_url_secrets("myweb.com/t/my-12345-token/test.repo")
        == "myweb.com/test.repo"
    )
    # Don't get fooled by '@' that appears after the path separator.
    assert (
        libmamba_strip_url_secrets("myweb.com/path/with@in-it/foo")
        == "myweb.com/path/with@in-it/foo"
    )


def test_libmamba_strip_url_secrets_token_without_trailing_slash():
    """libmamba's token regex matches ``/t/<token>`` whether or not there's
    a trailing path component; the previous regex required a trailing
    slash, leaving terminal-token URLs untouched."""
    assert (
        libmamba_strip_url_secrets("https://repo.com/t/my-token") == "https://repo.com"
    )
    assert (
        libmamba_strip_url_secrets("https://repo.com/t/my-token/path")
        == "https://repo.com/path"
    )


def test_libmamba_strip_url_secrets_token_regex_is_intentionally_overreaching():
    """Pin the slightly weird-looking behavior so a future cleanup
    doesn't quietly diverge from libmamba's cache path derivation.

    libmamba's regex (``/t/([a-zA-Z0-9-_]{0,2}[a-zA-Z0-9-]*)``) treats
    *any* ``/t/<chars>`` path component as an auth token and removes it.
    A path like ``/not/t/pkg.conda`` therefore loses the ``/t/pkg``
    segment. We deliberately match that behavior so our cache lookup
    derives the same path mamba 2.6.0 wrote -- correctness with respect
    to the cache, not generic URL sanitization.
    """
    assert (
        libmamba_strip_url_secrets("https://repo.com/not/t/pkg.conda")
        == "https://repo.com/not.conda"
    )


def test_normalize_url_for_compare_force_https_strip_slash():
    """The normalized form drops scheme differences and trailing slashes."""
    assert normalize_url_for_compare(
        "http://conda.example.com/c/linux-64/foo.conda"
    ) == normalize_url_for_compare("https://conda.example.com/c/linux-64/foo.conda/")
    assert normalize_url_for_compare(
        "https://user:pw@conda.example.com/c/linux-64/foo.conda"
    ) == normalize_url_for_compare("https://conda.example.com/c/linux-64/foo.conda")


# ---------------------------------------------------------------------------
# hierarchical_cache_subpath
# ---------------------------------------------------------------------------


def test_hierarchical_cache_subpath_from_url():
    """The cache subpath is derived from the package URL, not a glob."""
    sub = hierarchical_cache_subpath(_MAMBA_26_LINK_ACTION)
    assert sub == Path("https/conda.anaconda.org/conda-forge/linux-64")


def test_hierarchical_cache_subpath_from_base_url_and_platform():
    """Falls back to base_url + platform when the URL is absent."""
    sparse = {
        "base_url": "https://conda.anaconda.org/conda-forge",
        "platform": "linux-64",
    }
    assert hierarchical_cache_subpath(sparse) == Path(
        "https/conda.anaconda.org/conda-forge/linux-64"
    )


def test_hierarchical_cache_subpath_strips_duplicated_platform_suffix():
    """``base_url`` may already include the subdir; don't double it up."""
    sparse = {
        "base_url": "https://conda.anaconda.org/conda-forge/linux-64",
        "platform": "linux-64",
    }
    assert hierarchical_cache_subpath(sparse) == Path(
        "https/conda.anaconda.org/conda-forge/linux-64"
    )


def test_hierarchical_cache_subpath_normalizes_port_separator():
    """Per mamba 2.6.0, a port's ``:`` is escaped to ``_``."""
    link = {"url": "http://localhost:8000/mychannel/noarch/foo-1.0-bld.conda"}
    assert hierarchical_cache_subpath(link) == Path(
        "http/localhost_8000/mychannel/noarch"
    )


def test_hierarchical_cache_subpath_strips_credentials():
    """Mamba feeds ``remove_secrets_and_login_credentials`` *before* path
    normalization, so userinfo and ``/t/<token>/`` segments must not appear
    in the cache path. Otherwise the fallback misses authenticated channels
    even when mamba cached the package correctly."""
    with_userinfo = {
        "url": "https://user:secret@conda.example.com/private/linux-64/foo.conda"
    }
    assert hierarchical_cache_subpath(with_userinfo) == Path(
        "https/conda.example.com/private/linux-64"
    )
    with_token = {
        "url": "https://conda.anaconda.org/t/aa-bbb-ccc/private/linux-64/foo.conda"
    }
    assert hierarchical_cache_subpath(with_token) == Path(
        "https/conda.anaconda.org/private/linux-64"
    )


# ---------------------------------------------------------------------------
# record_matches_link
# ---------------------------------------------------------------------------


def test_record_matches_link_validates_identity():
    record = {
        "name": "zlib",
        "version": "1.3.2",
        "subdir": "linux-64",
        "sha256": "abc",
        "md5": "111",
        "fn": "zlib-1.3.2-bld.conda",
        "url": "https://conda.anaconda.org/conda-forge/linux-64/zlib-1.3.2-bld.conda",
        "channel": "conda-forge",
    }
    link = {
        "name": "zlib",
        "version": "1.3.2",
        "platform": "linux-64",
        "sha256": "abc",
        "md5": "111",
        "fn": "zlib-1.3.2-bld.conda",
        "url": "https://conda.anaconda.org/conda-forge/linux-64/zlib-1.3.2-bld.conda",
        "channel": "conda-forge",
    }
    assert _matched(record, link)
    # Every concrete identity field is enforced.
    assert not _matched({**record, "version": "9.9.9"}, link)
    assert not _matched({**record, "subdir": "osx-64"}, link)
    assert not _matched({**record, "sha256": "deadbeef"}, link)
    assert not _matched({**record, "md5": "deadbeef"}, link)
    assert not _matched({**record, "fn": "other.conda"}, link)
    assert not _matched(
        {**record, "url": "https://other.example.com/c/linux-64/x.conda"}, link
    )


def test_record_matches_link_url_takes_precedence_over_channel():
    """libmamba: when the record carries a URL, validate the URL and DON'T
    fall back to channel-string compare. Mirrored / aliased channels can
    legitimately spell their channel string differently while pointing at
    the same artifact URL."""
    name_version = {"name": "foo", "version": "1.0"}
    url = "https://conda.anaconda.org/conda-forge/linux-64/foo.conda"
    record = {
        **name_version,
        "url": url,
        "channel": "https://conda.anaconda.org/conda-forge",
    }
    link = {**name_version, "url": url, "channel": "conda-forge"}
    assert _matched(record, link)


def test_record_matches_link_falls_back_to_channel_when_record_url_empty():
    """libmamba: only when the record has no URL, validate the channel
    string. A channel mismatch in that fallback DOES reject."""
    name_version = {"name": "foo", "version": "1.0"}
    record = {**name_version, "channel": "conda-forge"}
    link = {**name_version, "channel": "conda-forge"}
    assert _matched(record, link)
    assert not _matched({**name_version, "channel": "other"}, link)


def test_record_matches_link_url_compare_matches_libmamba():
    """libmamba's ``compare_cleaned_url`` parses both URLs, forces scheme
    to ``https``, strips credentials, and trims trailing slashes before
    comparing. Differences libmamba considers equivalent must not reject."""
    name_version = {"name": "foo", "version": "1.0"}
    record = {**name_version, "url": "http://conda.example.com/c/linux-64/foo.conda"}
    link = {**name_version, "url": "https://conda.example.com/c/linux-64/foo.conda"}
    assert _matched(record, link)
    record = {**name_version, "url": "https://conda.example.com/c/linux-64/foo.conda/"}
    link = {**name_version, "url": "https://conda.example.com/c/linux-64/foo.conda"}
    assert _matched(record, link)
    record = {
        **name_version,
        "url": "https://user:pass@conda.example.com/c/linux-64/foo.conda",
    }
    link = {**name_version, "url": "https://conda.example.com/c/linux-64/foo.conda"}
    assert _matched(record, link)


def test_record_matches_link_returns_reason_for_diagnostic():
    """Failure reasons should be specific so the production log isn't an
    archaeology project later."""
    record = {"name": "foo", "version": "1.0", "sha256": "abc"}
    link = {"name": "foo", "version": "1.0", "sha256": "deadbeef"}
    matched, reason = record_matches_link(record, link)
    assert not matched
    assert reason and "sha256" in reason


# ---------------------------------------------------------------------------
# candidate_record_paths and get_repodata_record
# ---------------------------------------------------------------------------


def test_candidate_record_paths_are_metadata_derived(tmp_path: Path):
    """Candidate paths are computed from LINK metadata, never globbed."""
    candidates = candidate_record_paths(
        tmp_path, "libzlib-1.3.2-h25fd6f3_2", _MAMBA_26_LINK_ACTION
    )
    assert candidates == [
        tmp_path
        / "https/conda.anaconda.org/conda-forge/linux-64"
        / "libzlib-1.3.2-h25fd6f3_2"
        / "info"
        / "repodata_record.json",
        tmp_path / "libzlib-1.3.2-h25fd6f3_2" / "info" / "repodata_record.json",
    ]


def test_get_repodata_record_legacy_layout(tmp_path: Path):
    """Pre-2.6 mamba and conda still use the flat ``<pkgs>/<dist>/info`` layout."""
    flat = tmp_path / "flat"
    _write_record(
        flat / "foo-1.0.0-bld" / "info" / "repodata_record.json",
        name="foo",
        version="1.0.0",
        subdir="linux-64",
    )
    lookup = get_repodata_record(
        [flat],
        "foo-1.0.0-bld",
        {"name": "foo", "version": "1.0.0", "platform": "linux-64"},
    )
    assert lookup.outcome == "found"
    assert lookup.record == {"name": "foo", "version": "1.0.0", "subdir": "linux-64"}


def test_get_repodata_record_hierarchical_layout(tmp_path: Path):
    """Mamba 2.6.0 hierarchical layout: pkgs/<channel-url>/<platform>/<dist>/info."""
    hier = tmp_path / "hier"
    _write_record(
        hier
        / "https/conda.anaconda.org/conda-forge/linux-64"
        / "libzlib-1.3.2-h25fd6f3_2"
        / "info"
        / "repodata_record.json",
        name="libzlib",
        version="1.3.2",
        subdir="linux-64",
        sha256=_MAMBA_26_LINK_ACTION["sha256"],
        url=_MAMBA_26_LINK_ACTION["url"],
    )
    lookup = get_repodata_record(
        [hier], "libzlib-1.3.2-h25fd6f3_2", _MAMBA_26_LINK_ACTION
    )
    assert lookup.outcome == "found"
    assert lookup.record is not None
    assert lookup.record["url"] == _MAMBA_26_LINK_ACTION["url"]


def test_get_repodata_record_rejects_cross_channel_collision(tmp_path: Path):
    """A different package with the same dist_name in a different channel must
    NOT be returned. Mamba 2.6.0's hierarchy exists precisely to disambiguate
    such collisions; conda-lock must not silently pick the wrong record."""
    pkgs = tmp_path / "pkgs"
    _write_record(
        pkgs
        / "https/repo.example.com/private/linux-64"
        / "libzlib-1.3.2-h25fd6f3_2"
        / "info"
        / "repodata_record.json",
        name="libzlib",
        version="9.9.9",
        subdir="linux-64",
        sha256="deadbeef",
        url="https://repo.example.com/private/linux-64/libzlib-1.3.2-h25fd6f3_2.conda",
    )
    lookup = get_repodata_record(
        [pkgs], "libzlib-1.3.2-h25fd6f3_2", _MAMBA_26_LINK_ACTION
    )
    assert lookup.outcome == "not_found"
    assert lookup.record is None


# --- 1. Corruption detection + heal -------------------------------------


def test_get_repodata_record_skips_unparseable_candidate(tmp_path):
    """A half-written/garbled candidate is skipped, not fatal: the flat
    fallback still serves the good record, mirroring the transient
    partial-write race the retry loop exists for."""
    link = dict(_MAMBA_26_LINK_ACTION)
    dist_name = "libzlib-1.3.2-h25fd6f3_2"
    pkgs_dir = tmp_path / "pkgs"
    hier_dir = (
        pkgs_dir / "https/conda.anaconda.org/conda-forge/linux-64" / dist_name / "info"
    )
    hier_dir.mkdir(parents=True)
    (hier_dir / "repodata_record.json").write_text('{"truncated": ')
    flat_dir = pkgs_dir / dist_name / "info"
    flat_dir.mkdir(parents=True)
    (flat_dir / "repodata_record.json").write_text(json.dumps(link))
    lookup = get_repodata_record([pkgs_dir], dist_name, link)
    assert lookup.outcome == "found"
    assert lookup.record is not None
    assert lookup.record["sha256"] == link["sha256"]


def test_get_repodata_record_reports_unparseable_only_candidate(tmp_path):
    """When every candidate is unreadable, the failure is surfaced: the
    not_found reason carries the parse error rather than a bare
    file-not-found."""
    link = dict(_MAMBA_26_LINK_ACTION)
    dist_name = "libzlib-1.3.2-h25fd6f3_2"
    pkgs_dir = tmp_path / "pkgs"
    flat_dir = pkgs_dir / dist_name / "info"
    flat_dir.mkdir(parents=True)
    (flat_dir / "repodata_record.json").write_text("not json at all")
    lookup = get_repodata_record([pkgs_dir], dist_name, link)
    assert lookup.outcome == "not_found"
    assert lookup.record is None
    assert "failed to read" in (lookup.reason or "")
