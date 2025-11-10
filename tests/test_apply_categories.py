from pathlib import Path

import pytest

from conda_lock.conda_solver import solve_conda
from conda_lock.lockfile import apply_categories
from conda_lock.lookup import DEFAULT_MAPPING_URL
from conda_lock.models.channel import Channel
from conda_lock.models.lock_spec import VersionedDependency


def test_apply_categories_missing_solver_dependency(
    mamba_exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Disabling ``add_pip_as_python_dependency`` causes some conda-based solvers to drop
    ``pip`` from the planned package set even though the python package metadata still
    lists it as a dependency (see GH-843). Ensure that we gracefully skip any missing
    dependencies instead of raising ``KeyError``.
    """

    monkeypatch.setenv("CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY", "false")

    specs = {
        "python": VersionedDependency(name="python", version="3.12.*"),
        "pytest": VersionedDependency(name="pytest", version="8.*"),
    }

    planned = solve_conda(
        conda=mamba_exe,
        specs=specs,
        locked={},
        update=[],
        platform="linux-64",
        channels=[Channel.from_string("defaults")],
        mapping_url=DEFAULT_MAPPING_URL,
    )

    # Some solver stacks (e.g. conda classic with libsolv) still report ``pip`` as a
    # dependency even when CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY disables the automatic
    # installation. Recreate that scenario by injecting the dependency and then removing
    # the concrete package from the planned fetch set.
    planned["python"].dependencies["pip"] = ""

    planned_without_pip = {name: dep for name, dep in planned.items() if name != "pip"}
    assert "pip" not in planned_without_pip

    apply_categories(
        requested=specs,
        planned=planned_without_pip,
        mapping_url=DEFAULT_MAPPING_URL,
    )

    assert planned_without_pip["python"].categories == {"main"}
