from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from conda_lock._vendor.poetry.plugins.base_plugin import BasePlugin


if TYPE_CHECKING:
    from conda_lock._vendor.cleo.io.io import IO

    from conda_lock._vendor.poetry.poetry import Poetry


class Plugin(BasePlugin):
    """
    Generic plugin not related to the console application.
    """

    group = "poetry.plugin"

    @abstractmethod
    def activate(self, poetry: Poetry, io: IO) -> None: ...
