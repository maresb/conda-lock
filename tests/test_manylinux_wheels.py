"""Check newer manylinux wheels against the target glibc, not the host."""

import pytest

from packaging.utils import parse_wheel_filename
from packaging.version import Version

from conda_lock.pypi_solver import PlatformEnv
from conda_lock.virtual_package import VirtualPackage


@pytest.mark.parametrize(
    ("platform", "wheel", "minimum_glibc"),
    [
        (
            "linux-64",
            "pyqir-0.12.3-cp39-abi3-manylinux_2_34_x86_64.whl",
            "2.34",
        ),
        (
            "linux-aarch64",
            "pyqir-0.12.3-cp39-abi3-manylinux_2_38_aarch64.whl",
            "2.38",
        ),
    ],
)
@pytest.mark.parametrize("glibc_version", ["2.28", "2.33", "2.34", "2.37", "2.38"])
def test_newer_manylinux_wheel_compatibility(
    platform: str, wheel: str, minimum_glibc: str, glibc_version: str
) -> None:
    """The wheels from #900 require an explicit sufficiently new glibc target."""
    glibc = VirtualPackage(name="__glibc", version=glibc_version)
    env = PlatformEnv(
        platform=platform,
        python_version="3.11",
        platform_virtual_packages=dict([glibc.to_repodata_entry(subdir=platform)]),
    )
    wheel_tags = parse_wheel_filename(wheel)[3]
    compatible = bool(wheel_tags.intersection(env.get_supported_tags()))
    assert compatible == (Version(glibc_version) >= Version(minimum_glibc))
