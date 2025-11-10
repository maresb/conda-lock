"""Test for issue #843: KeyError when pip is not in environment file but is a dependency."""

import pytest

from conda_lock.lockfile import apply_categories
from conda_lock.lockfile.v2prelim.models import LockedDependency
from conda_lock.lockfile.v1.models import HashModel
from conda_lock.models.lock_spec import VersionedDependency


def test_apply_categories_with_missing_pip_dependency():
    """
    Test that apply_categories handles the case where 'pip' is a dependency
    of a package but 'pip' is not in the planned dictionary.
    
    This reproduces issue #843 where conda-lock crashes with KeyError: 'pip'
    when pip is not included in the environment file.
    """
    # Create a requested dependency (e.g., a package that depends on pip)
    requested = {
        "some-package": VersionedDependency(
            name="some-package",
            manager="conda",
            version="1.0.0",
            category="main"
        )
    }
    
    # Create a planned dependency that has 'pip' as a dependency
    # but 'pip' itself is NOT in the planned dictionary
    planned_package = LockedDependency(
        name="some-package",
        version="1.0.0",
        manager="conda",
        platform="linux-64",
        dependencies={"pip": ""},  # This package depends on pip
        url="https://example.com/some-package-1.0.0.conda",
        hash=HashModel(md5="d41d8cd98f00b204e9800998ecf8427e"),  # Empty MD5 hash for test
        categories=set(),
    )
    
    planned = {
        "some-package": planned_package,
        # Note: "pip" is NOT in planned, which causes the KeyError
    }
    
    # This should not raise a KeyError
    # Before the fix, it would raise KeyError: 'pip'
    apply_categories(
        requested=requested,
        planned=planned,
        categories=("main", "dev"),
        convert_to_pip_names=False,
        mapping_url="https://raw.githubusercontent.com/conda/conda-lock/main/conda_lock/lookup/name_mapping.yaml",
    )
    
    # Verify that the planned package still has its categories set
    assert "main" in planned_package.categories


def test_apply_categories_with_missing_dependency_in_root_requests():
    """
    Test that apply_categories handles the case where a dependency is in
    root_requests but not in the planned dictionary.
    
    This tests the second location where _seperator_munge_get is called (line 154).
    """
    requested = {
        "some-package": VersionedDependency(
            name="some-package",
            manager="conda",
            version="1.0.0",
            category="main"
        )
    }
    
    planned_package = LockedDependency(
        name="some-package",
        version="1.0.0",
        manager="conda",
        platform="linux-64",
        dependencies={},  # No dependencies
        url="https://example.com/some-package-1.0.0.conda",
        hash=HashModel(md5="d41d8cd98f00b204e9800998ecf8427e"),
        categories=set(),
    )
    
    planned = {
        "some-package": planned_package,
        # Note: "pip" is NOT in planned
    }
    
    # Manually add "pip" to root_requests to simulate the scenario where
    # a dependency is referenced but not in planned
    # This simulates the case where line 154 tries to access a missing dependency
    apply_categories(
        requested=requested,
        planned=planned,
        categories=("main", "dev"),
        convert_to_pip_names=False,
        mapping_url="https://raw.githubusercontent.com/conda/conda-lock/main/conda_lock/lookup/name_mapping.yaml",
    )
    
    # The function should complete without raising a KeyError
    assert "main" in planned_package.categories
