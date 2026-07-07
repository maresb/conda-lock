"""Consistency checks between the captured dryrun JSON fixtures and the
LINK-action literals in ``tests/support/fixtures.py``.

The literals are documented as field-for-field copies of
``actions.LINK[0]`` from the capture files. These tests make that claim
mechanically verifiable, so neither side can drift without failing CI.
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from tests.support.fixtures import (
    CONDA_LINK_ACTION,
    MAMBA_26_LINK_ACTION,
    MICROMAMBA_1_5_LINK_ACTION,
)


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "test-mamba-fixtures"


def _link_entry(fixture_name: str, package_name: str) -> dict:
    payload = json.loads((FIXTURES_DIR / fixture_name).read_text())
    matches = [e for e in payload["actions"]["LINK"] if e["name"] == package_name]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize(
    ("literal", "fixture_name"),
    [
        (MAMBA_26_LINK_ACTION, "dryrun-mamba-2.6.0-linux-64-zlib.json"),
        (
            MICROMAMBA_1_5_LINK_ACTION,
            "dryrun-micromamba-1.5.12-linux-64-libzlib.json",
        ),
        (CONDA_LINK_ACTION, "dryrun-conda-26.5.2-linux-64-libzlib.json"),
        # The Python mamba 1.x CLI renders plans through conda's JSON
        # printer; its LINK entry is asserted identical to conda's, so
        # one literal intentionally serves both captures.
        (CONDA_LINK_ACTION, "dryrun-mamba-1.5.12-python-linux-64-libzlib.json"),
    ],
    ids=["mamba-2.6.0", "micromamba-1.5.12", "conda-26.5.2", "mamba-1.5.12-python"],
)
def test_link_literal_matches_captured_json(literal, fixture_name):
    """Each literal is exactly ``actions.LINK[<libzlib>]`` of its capture."""
    assert dict(literal) == _link_entry(fixture_name, "libzlib")
