import re
import shutil
import subprocess
import tempfile

from itertools import chain
from pathlib import Path

from migrate_code import Migration, get_repo_root

from conda_lock.vendor.scripts.poetry.vendor_helpers import (
    DependencyData,
    Requirement,
    merge_requirements,
    req_to_req_obj,
)


m = Migration("Vendor poetry")

directly_vendored_dependencies = {
    "cleo": DependencyData(
        name="cleo",
        version="0.8.1",
        sha256="3d0e22d30117851b45970b6c14aca4ab0b18b1b53c8af57bed13208147e4069f",
    ),
    "poetry": DependencyData(
        name="poetry",
        version="1.1.15",
        sha256="a373848fd205f31b2f6bee6b87a201ea1e09ca573a2f40d0991539f564cedffd",
    ),
    "poetry-core": DependencyData(
        name="poetry-core",
        version="1.0.8",
        sha256="951fc7c1f8d710a94cb49019ee3742125039fc659675912ea614ac2aa405b118",
    ),
}


def get_vendor_root() -> Path:
    return get_repo_root() / "conda_lock" / "vendor"


@m.add_stage(1, "Add root LICENSE files for main Poetry packages")
def add_poetry_root_licenses() -> None:
    """Add the root licenses for Poetry, Poetry Core, and Cleo.

    Copy them to "vendor/licenses/packagename/LICENSE".
    They are all MIT licenses.
    This does not deal with the vendored dependencies of Poetry Core.
    """
    vendor_root = get_vendor_root()  # conda_lock/vendor/
    for dep_data in directly_vendored_dependencies.values():
        license = dep_data._root_license
        assert license.is_mit
        destination_dir = vendor_root / "licenses" / dep_data.name
        destination_dir.mkdir(parents=True, exist_ok=True)
        (destination_dir / "LICENSE").write_text(license.text)


@m.add_stage(2, "Describe vendored dependencies in conda-lock LICENSE")
def collect_poetry_core_vendored_dependencies() -> None:
    """Collect info about poetry-core's vendored dependencies.

    Also show that there aren't any vendored dependencies in poetry.

    (We only need to vendor a single file from cleo, so its vendored
    dependencies are not relevant.)
    """
    # The only vendored dependencies should exist in poetry-core.
    for dep_name, dep in directly_vendored_dependencies.items():
        dep.discovered_licenses = [dep._root_license]
        if dep_name == "poetry-core":
            continue
        discovered_vendored_dependencies = dep.search_vendored_dependencies()
        assert len(discovered_vendored_dependencies) == 0

    poetry_core = directly_vendored_dependencies["poetry-core"]
    discovered_vendored_dependencies = poetry_core.search_vendored_dependencies()

    conda_lock_license_file = get_repo_root() / "LICENSE"
    conda_lock_license = conda_lock_license_file.read_text()
    conda_lock_license = conda_lock_license.replace("license as", "licensed as")
    conda_lock_license = conda_lock_license.replace(
        "Conda-lock incorporates the following libraries into",
        "Conda-lock incorporates the following libraries, "
        "sometimes with modification, into",
    )
    conda_lock_license += "\n".join(
        [f"* {dep.describe()}" for dep in directly_vendored_dependencies.values()]
    )
    conda_lock_license += "\n"
    # Print subdependencies of poetry-core at the next level of indentation.
    assert list(directly_vendored_dependencies.keys())[-1] == "poetry-core"
    conda_lock_license += "\n".join(
        [f"  * {dep.describe()}" for dep in discovered_vendored_dependencies.values()]
    )
    conda_lock_license += "\n"
    conda_lock_license_file.write_text(conda_lock_license)


@m.add_stage(3, "Add vendored dependency requirements to conda-lock")
def add_vendored_requirements() -> None:
    # The list of requirements which we should add
    relevant_requirements: list[Requirement] = []

    # Iterate over cleo, poetry, and poetry-core
    for dep in directly_vendored_dependencies.values():
        # Get the list of requirements as a list of strings.
        # Typical string: ('cachecontrol[filecache] (>=0.12.9,<0.13.0); '
        #                  'python_version >= "3.6" and python_version < "4.0"')
        req_list = dep._sdist_obj.requires_dist

        for req_str in req_list:
            req: Requirement | None = req_to_req_obj(req_str, dep)
            if req is None:
                continue
            else:
                relevant_requirements.append(req)

    # Some of the requirements may occur multiple times, so we should merge them.
    merged_requirements: dict[str, Requirement] = merge_requirements(
        relevant_requirements
    )
    # Filter out the directly vendored dependencies
    filtered_requirements = {
        k: v
        for k, v in merged_requirements.items()
        if k not in directly_vendored_dependencies
    }

    # Update the requirements.txt file

    requirements_txt_file = get_repo_root() / "requirements.txt"
    requirements_txt = requirements_txt_file.read_text()

    # Remove some requirements which are redundant
    for line in ["poetry <1.2", "requests >=2"]:
        requirements_txt = requirements_txt.replace(line + "\n", "")
    filtered_requirements["requests"].sources.append("conda-lock")

    for requirement in filtered_requirements.values():
        # Construct the line to append to requirements.txt.
        # e.g. 'importlib-metadata >=1.7.0,<2.0.0; '
        #      'python_version <= 3.7  # poetry, poetry-core'
        requirement_line = requirement.as_requirements_txt_line()
        requirements_txt += requirement_line + "\n"

    requirements_txt_file.write_text(requirements_txt)


@m.add_stage(4, "Vendor IOMixin from cleo.io.io_mixin")
def vendor_io_mixin() -> None:
    dest_dir = get_vendor_root() / "cleo" / "io"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Get a temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.check_output(
            [
                "pip",
                "install",
                "--no-deps",
                "--target",
                tmpdir,
                f"cleo=={directly_vendored_dependencies['cleo'].version}",
            ]
        )
        io_mixin = Path(tmpdir) / "cleo" / "io" / "io_mixin.py"
        io_mixin.rename(dest_dir / "io_mixin.py")


def clean_dir(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            if child.name == "__pycache__":
                shutil.rmtree(child)
            else:
                clean_dir(child)
        else:
            raise RuntimeError(f"Unexpected file: {child}")
    path.rmdir()


@m.add_stage(5, "Vendor poetry.core")
def vendor_poetry_core() -> None:
    destination_dir = get_vendor_root() / "poetry_core"
    if destination_dir.exists():
        clean_dir(destination_dir)
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.check_output(
            [
                "pip",
                "install",
                "--no-deps",
                "--target",
                tmpdir,
                f"poetry-core=={directly_vendored_dependencies['poetry-core'].version}",
            ]
        )
        shutil.move(Path(tmpdir) / "poetry" / "core", destination_dir)


@m.add_stage(6, "Vendor poetry")
def vendor_poetry() -> None:
    destination_dir = get_vendor_root() / "poetry"
    if destination_dir.exists():
        clean_dir(destination_dir)
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.check_output(
            [
                "pip",
                "install",
                "--no-deps",
                "--target",
                tmpdir,
                f"poetry=={directly_vendored_dependencies['poetry'].version}",
            ]
        )
        shutil.move(Path(tmpdir) / "poetry", destination_dir)


@m.add_stage(7, "Update imports to use vendored poetry-core and cleo")
def modify_vendored_imports() -> None:
    for src_file in chain(
        (get_vendor_root() / "poetry").rglob("*.py"),
        (get_vendor_root() / "poetry_core").rglob("*.py"),
        [get_repo_root() / "conda_lock" / "pypi_solver.py"],
    ):
        src = src_file.read_text()
        src = src.replace(" cleo.", " conda_lock.vendor.cleo.")
        src = src.replace(" poetry.core.", " conda_lock.vendor.poetry_core.")
        src = src.replace("(poetry.core.", "(conda_lock.vendor.poetry_core.")
        src = src.replace(" poetry.", " conda_lock.vendor.poetry.")
        src = src.replace("(poetry.", "(conda_lock.vendor.poetry.")
        src_file.write_text(src)
    subprocess.run(
        [
            "pre-commit",
            "run",
            "--files",
            get_repo_root() / "conda_lock" / "pypi_solver.py",
        ]
    )


@m.add_stage(8, "Generate temporary requirements.txt for poetry with pipreqs")
def generate_pipreqs_requirements_txt() -> None:
    subprocess.check_output(["pipreqs", str(get_vendor_root() / "poetry")])


@m.add_stage(9, "Delete poetry.console, poetry.publishing, poetry.utils.shell")
def delete_poetry_console() -> None:
    shutil.rmtree(get_vendor_root() / "poetry" / "console")
    shutil.rmtree(get_vendor_root() / "poetry" / "publishing")
    (get_vendor_root() / "poetry" / "utils" / "shell.py").unlink()


@m.add_stage(10, "Regenerate requirements.txt for poetry with pipreqs")
def regenerate_pipreqs_requirements_txt() -> None:
    (get_vendor_root() / "poetry" / "requirements.txt").unlink()
    subprocess.check_output(["pipreqs", str(get_vendor_root() / "poetry")])


@m.add_stage(11, "Remove pexpect, requests_toolbelt, and shellingham as dependencies")
def remove_unnecessary_dependencies() -> None:
    poetry_requirements_txt_file = get_vendor_root() / "poetry" / "requirements.txt"
    diff = subprocess.check_output(
        ["git", "diff", "@~1", poetry_requirements_txt_file]
    ).decode()
    to_remove: list[str] = []
    for line in diff.splitlines():
        if line.startswith("-") and "==" in line:
            pkg_name = line.split("==")[0].strip("- ").replace("_", "-")
            if pkg_name != "cleo":
                to_remove.append(pkg_name)

    assert set(to_remove) == {"pexpect", "requests-toolbelt", "shellingham"}

    conda_lock_requirements_txt = (get_repo_root() / "requirements.txt").read_text()
    new_requirements_txt = ""
    for line in conda_lock_requirements_txt.splitlines():
        if any(line.startswith(f"{pkg_name} ") for pkg_name in to_remove):
            continue
        new_requirements_txt += line + "\n"
    (get_repo_root() / "requirements.txt").write_text(new_requirements_txt)


@m.add_stage(12, "Remove temporary pipreqs requirements.txt for poetry")
def remove_pipreqs_requirements_txt() -> None:
    (get_vendor_root() / "poetry" / "requirements.txt").unlink()


@m.add_stage(13, "Remove upper bounds on poetry dependencies")
def remove_upper_bounds() -> None:
    conda_lock_requirements_txt = (get_repo_root() / "requirements.txt").read_text()
    new_requirements = ""
    for line in conda_lock_requirements_txt.splitlines():
        if ",<" in line and "#" in line and "poetry" in line.split("#")[1]:
            line = re.sub(r",<[0-9.]+", "", line)
        new_requirements += line + "\n"
    (get_repo_root() / "requirements.txt").write_text(new_requirements)
