from __future__ import annotations

import dataclasses
import logging
import os
import re

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar

from packaging.utils import canonicalize_name

from conda_lock._vendor.poetry.config.dict_config_source import DictConfigSource
from conda_lock._vendor.poetry.config.file_config_source import FileConfigSource
from conda_lock._vendor.poetry.locations import CONFIG_DIR
from conda_lock._vendor.poetry.locations import DEFAULT_CACHE_DIR
from conda_lock._vendor.poetry.toml import TOMLFile


if TYPE_CHECKING:
    from collections.abc import Callable

    from conda_lock._vendor.poetry.config.config_source import ConfigSource


def boolean_validator(val: str) -> bool:
    return val in {"true", "false", "1", "0"}


def boolean_normalizer(val: str) -> bool:
    return val in ["true", "1"]


def int_normalizer(val: str) -> int:
    return int(val)


@dataclasses.dataclass
class PackageFilterPolicy:
    policy: dataclasses.InitVar[str | list[str] | None]
    packages: list[str] = dataclasses.field(init=False)

    def __post_init__(self, policy: str | list[str] | None) -> None:
        if not policy:
            policy = []
        elif isinstance(policy, str):
            policy = self.normalize(policy)
        self.packages = policy

    def allows(self, package_name: str) -> bool:
        if ":all:" in self.packages:
            return False

        return (
            not self.packages
            or ":none:" in self.packages
            or canonicalize_name(package_name) not in self.packages
        )

    @classmethod
    def is_reserved(cls, name: str) -> bool:
        return bool(re.match(r":(all|none):", name))

    @classmethod
    def normalize(cls, policy: str) -> list[str]:
        if boolean_validator(policy):
            if boolean_normalizer(policy):
                return [":all:"]
            else:
                return [":none:"]

        return list(
            {
                name.strip() if cls.is_reserved(name) else canonicalize_name(name)
                for name in policy.strip().split(",")
                if name
            }
        )

    @classmethod
    def validator(cls, policy: str) -> bool:
        if boolean_validator(policy):
            return True

        names = policy.strip().split(",")

        for name in names:
            if (
                not name
                or (cls.is_reserved(name) and len(names) == 1)
                or re.match(r"^[a-zA-Z\d_-]+$", name)
            ):
                continue
            return False

        return True


logger = logging.getLogger(__name__)

_default_config: Config | None = None


class Config:
    default_config: ClassVar[dict[str, Any]] = {
        "cache-dir": str(DEFAULT_CACHE_DIR),
        "virtualenvs": {
            "create": True,
            "in-project": None,
            "path": os.path.join("{cache-dir}", "virtualenvs"),
            "options": {
                "always-copy": False,
                "system-site-packages": False,
                "no-pip": False,
            },
            "use-poetry-python": False,
            "prompt": "{project_name}-py{python_version}",
        },
        "requests": {
            "max-retries": 0,
        },
        "installer": {
            "re-resolve": True,
            "parallel": True,
            "max-workers": None,
            "no-binary": None,
            "only-binary": None,
        },
        "solver": {
            "lazy-wheel": True,
        },
        "system-git-client": False,
        "keyring": {
            "enabled": True,
        },
    }

    def __init__(self, use_environment: bool = True) -> None:
        self._config = deepcopy(self.default_config)
        self._use_environment = use_environment
        self._config_source: ConfigSource = DictConfigSource()
        self._auth_config_source: ConfigSource = DictConfigSource()

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def config_source(self) -> ConfigSource:
        return self._config_source

    @property
    def auth_config_source(self) -> ConfigSource:
        return self._auth_config_source

    def set_config_source(self, config_source: ConfigSource) -> Config:
        self._config_source = config_source

        return self

    def set_auth_config_source(self, config_source: ConfigSource) -> Config:
        self._auth_config_source = config_source

        return self

    def merge(self, config: dict[str, Any]) -> None:
        from conda_lock._vendor.poetry.utils.helpers import merge_dicts

        merge_dicts(self._config, config)

    def all(self) -> dict[str, Any]:
        def _all(config: dict[str, Any], parent_key: str = "") -> dict[str, Any]:
            all_ = {}

            for key in config:
                value = self.get(parent_key + key)
                if isinstance(value, dict):
                    if parent_key != "":
                        current_parent = parent_key + key + "."
                    else:
                        current_parent = key + "."
                    all_[key] = _all(config[key], parent_key=current_parent)
                    continue

                all_[key] = value

            return all_

        return _all(self.config)

    def raw(self) -> dict[str, Any]:
        return self._config

    @staticmethod
    def _get_environment_repositories() -> dict[str, dict[str, str]]:
        repositories = {}
        pattern = re.compile(r"POETRY_REPOSITORIES_(?P<name>[A-Z_]+)_URL")

        for env_key in os.environ:
            match = pattern.match(env_key)
            if match:
                repositories[match.group("name").lower().replace("_", "-")] = {
                    "url": os.environ[env_key]
                }

        return repositories

    @property
    def repository_cache_directory(self) -> Path:
        return Path(self.get("cache-dir")).expanduser() / "cache" / "repositories"

    @property
    def artifacts_cache_directory(self) -> Path:
        return Path(self.get("cache-dir")).expanduser() / "artifacts"

    @property
    def virtualenvs_path(self) -> Path:
        path = self.get("virtualenvs.path")
        if path is None:
            path = Path(self.get("cache-dir")) / "virtualenvs"
        return Path(path).expanduser()

    @property
    def installer_max_workers(self) -> int:
        # This should be directly handled by ThreadPoolExecutor
        # however, on some systems the number of CPUs cannot be determined
        # (it raises a NotImplementedError), so, in this case, we assume
        # that the system only has one CPU.
        try:
            default_max_workers = (os.cpu_count() or 1) + 4
        except NotImplementedError:
            default_max_workers = 5

        desired_max_workers = self.get("installer.max-workers")
        if desired_max_workers is None:
            return default_max_workers
        return min(default_max_workers, int(desired_max_workers))

    def get(self, setting_name: str, default: Any = None) -> Any:
        """
        Retrieve a setting value.
        """
        keys = setting_name.split(".")

        # Looking in the environment if the setting
        # is set via a POETRY_* environment variable
        if self._use_environment:
            if setting_name == "repositories":
                # repositories setting is special for now
                repositories = self._get_environment_repositories()
                if repositories:
                    return repositories

            env = "POETRY_" + "_".join(k.upper().replace("-", "_") for k in keys)
            env_value = os.getenv(env)
            if env_value is not None:
                return self.process(self._get_normalizer(setting_name)(env_value))

        value = self._config
        for key in keys:
            if key not in value:
                return self.process(default)

            value = value[key]

        if self._use_environment and isinstance(value, dict):
            # this is a configuration table, it is likely that we missed env vars
            # in order to capture them recurse, eg: virtualenvs.options
            return {k: self.get(f"{setting_name}.{k}") for k in value}

        return self.process(value)

    def process(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        def resolve_from_config(match: re.Match[str]) -> Any:
            key = match.group(1)
            config_value = self.get(key)
            if config_value:
                return config_value

            # The key doesn't exist in the config but might be resolved later,
            # so we keep it as a format variable.
            return f"{{{key}}}"

        return re.sub(r"{(.+?)}", resolve_from_config, value)

    @staticmethod
    def _get_normalizer(name: str) -> Callable[[str], Any]:
        if name in {
            "virtualenvs.create",
            "virtualenvs.in-project",
            "virtualenvs.options.always-copy",
            "virtualenvs.options.no-pip",
            "virtualenvs.options.system-site-packages",
            "virtualenvs.use-poetry-python",
            "installer.re-resolve",
            "installer.parallel",
            "solver.lazy-wheel",
            "system-git-client",
            "keyring.enabled",
        }:
            return boolean_normalizer

        if name == "virtualenvs.path":
            return lambda val: str(Path(val))

        if name in {
            "installer.max-workers",
            "requests.max-retries",
        }:
            return int_normalizer

        if name in ["installer.no-binary", "installer.only-binary"]:
            return PackageFilterPolicy.normalize

        return lambda val: val

    @classmethod
    def create(cls, reload: bool = False) -> Config:
        global _default_config

        if _default_config is None or reload:
            _default_config = cls()

            # Load global config
            config_file = TOMLFile(CONFIG_DIR / "config.toml")
            if config_file.exists():
                logger.debug("Loading configuration file %s", config_file.path)
                _default_config.merge(config_file.read())

            _default_config.set_config_source(FileConfigSource(config_file))

            # Load global auth config
            auth_config_file = TOMLFile(CONFIG_DIR / "auth.toml")
            if auth_config_file.exists():
                logger.debug("Loading configuration file %s", auth_config_file.path)
                _default_config.merge(auth_config_file.read())

            _default_config.set_auth_config_source(FileConfigSource(auth_config_file))

        return _default_config
