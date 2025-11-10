from conda_lock.lockfile import apply_categories
from conda_lock.lockfile.v1.models import HashModel
from conda_lock.lockfile.v2prelim.models import LockedDependency
from conda_lock.lookup import DEFAULT_MAPPING_URL
from conda_lock.models.lock_spec import VersionedDependency


def test_apply_categories_handles_missing_transitive_dependency() -> None:
    requested = {
        "python": VersionedDependency(
            name="python",
            version="3.13.*",
            manager="conda",
            category="main",
        )
    }
    planned = {
        "python": LockedDependency(
            name="python",
            version="3.13.0",
            manager="conda",
            platform="linux-64",
            dependencies={"pip": ""},
            url="https://repo.anaconda.com/pkgs/main/linux-64/python-3.13.0-0.tar.bz2",
            hash=HashModel(md5="deadbeefdeadbeefdeadbeefdeadbeef"),
        )
    }

    apply_categories(
        requested=requested,
        planned=planned,
        mapping_url=DEFAULT_MAPPING_URL,
    )

    assert planned["python"].categories == {"main"}
