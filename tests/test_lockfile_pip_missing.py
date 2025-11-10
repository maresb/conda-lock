"""Test for issue #843: KeyError when pip is not in environment file but is a dependency.

The root cause is that conda-lock sets CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False,
which prevents pip from being automatically installed. However, Python's package
metadata lists pip as a dependency. When conda solves the environment, Python's
dependencies include pip, but since CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False,
pip won't actually be installed (won't be in the FETCH actions). When
apply_categories walks through the dependency tree, it encounters pip as a
dependency of Python but pip isn't in the planned dictionary, causing a KeyError.
"""

import pytest
from pathlib import Path

from conda_lock.conda_lock import run_lock
from conda_lock.lockfile import parse_conda_lock_file
from conda_lock.lockfile import apply_categories
from conda_lock.lockfile.v2prelim.models import LockedDependency
from conda_lock.lockfile.v1.models import HashModel
from conda_lock.models.lock_spec import VersionedDependency

TESTS_DIR = Path(__file__).parent


def test_lock_environment_without_pip_but_python_depends_on_it(
    tmp_path: Path, conda_exe: str, monkeypatch: pytest.MonkeyPatch
):
    """
    Test that conda-lock can lock an environment where Python depends on pip
    but pip is not explicitly included in the environment file.
    
    This reproduces issue #843 where conda-lock crashes with KeyError: 'pip'
    when pip is not included in the environment file but Python (which depends
    on pip) is included.
    """
    # Create an environment file with Python but no pip
    env_file = tmp_path / "environment.yml"
    env_file.write_text("""name: test-pip-missing
channels:
  - conda-forge
dependencies:
  - python=3.13
  - conda=25.7.0
  - pytest=8.4.1
  # Note: pip is NOT explicitly included, but Python depends on it
  # With CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False, pip won't be installed
  # but Python's metadata will still list it as a dependency
""")
    
    monkeypatch.chdir(tmp_path)
    
    # This should not raise a KeyError
    # Before the fix, it would raise KeyError: 'pip' in apply_categories
    run_lock(
        [env_file],
        conda_exe=conda_exe,
        platforms=["linux-64"],
        mapping_url="https://raw.githubusercontent.com/conda/conda-lock/main/conda_lock/lookup/name_mapping.yaml",
    )
    
    # Verify that the lockfile was created successfully
    lockfile_path = tmp_path / "conda-lock.yml"
    assert lockfile_path.exists()
    
    # Parse and verify the lockfile
    lockfile = parse_conda_lock_file(lockfile_path)
    assert lockfile is not None
    
    # Verify Python is in the lockfile
    python_packages = [p for p in lockfile.package if p.name == "python"]
    assert len(python_packages) > 0


def test_apply_categories_with_missing_pip_dependency():
    """
    Unit test that directly tests apply_categories with the scenario where
    Python depends on pip but pip is not in the planned dictionary.
    
    This simulates the exact scenario that occurs when:
    1. CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False (conda-lock's default)
    2. Python is in the environment (which depends on pip in its metadata)
    3. pip is not explicitly in the environment file
    4. pip won't be in the planned dictionary because it's not installed
    """
    # Create a requested dependency for Python
    requested = {
        "python": VersionedDependency(
            name="python",
            manager="conda",
            version="3.13.*",
            category="main"
        )
    }
    
    # Create a planned dependency for Python that has 'pip' as a dependency
    # (as Python's metadata does), but 'pip' itself is NOT in the planned dictionary
    # because CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False prevents it from being installed
    python_package = LockedDependency(
        name="python",
        version="3.13.0",
        manager="conda",
        platform="linux-64",
        dependencies={"pip": ""},  # Python depends on pip in its metadata
        url="https://conda.anaconda.org/conda-forge/linux-64/python-3.13.0.conda",
        hash=HashModel(md5="d41d8cd98f00b204e9800998ecf8427e"),
        categories=set(),
    )
    
    planned = {
        "python": python_package,
        # Note: "pip" is NOT in planned because CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY=False
        # prevents it from being installed, even though Python depends on it
    }
    
    # This should not raise a KeyError
    # Before the fix, it would raise KeyError: 'pip' when trying to look up
    # pip in the planned dictionary during the dependency tree walk
    apply_categories(
        requested=requested,
        planned=planned,
        categories=("main", "dev"),
        convert_to_pip_names=False,
        mapping_url="https://raw.githubusercontent.com/conda/conda-lock/main/conda_lock/lookup/name_mapping.yaml",
    )
    
    # Verify that Python still has its categories set
    assert "main" in python_package.categories


def test_apply_categories_with_missing_dependency_in_root_requests():
    """
    Test that apply_categories handles the case where a dependency is in
    root_requests but not in the planned dictionary.
    
    This tests the second location where _seperator_munge_get is called (line 161),
    where we try to assign categories to dependencies that are referenced but
    not actually installed.
    """
    requested = {
        "python": VersionedDependency(
            name="python",
            manager="conda",
            version="3.13.*",
            category="main"
        )
    }
    
    python_package = LockedDependency(
        name="python",
        version="3.13.0",
        manager="conda",
        platform="linux-64",
        dependencies={"pip": ""},  # Python depends on pip
        url="https://conda.anaconda.org/conda-forge/linux-64/python-3.13.0.conda",
        hash=HashModel(md5="d41d8cd98f00b204e9800998ecf8427e"),
        categories=set(),
    )
    
    planned = {
        "python": python_package,
        # Note: "pip" is NOT in planned
    }
    
    # This should complete without raising a KeyError when it tries to
    # assign categories to "pip" in root_requests (line 161)
    apply_categories(
        requested=requested,
        planned=planned,
        categories=("main", "dev"),
        convert_to_pip_names=False,
        mapping_url="https://raw.githubusercontent.com/conda/conda-lock/main/conda_lock/lookup/name_mapping.yaml",
    )
    
    # The function should complete successfully
    assert "main" in python_package.categories
