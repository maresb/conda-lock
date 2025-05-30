from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar

from conda_lock._vendor.cleo.helpers import argument
from conda_lock._vendor.cleo.helpers import option

from conda_lock._vendor.poetry.console.commands.init import InitCommand


if TYPE_CHECKING:
    from conda_lock._vendor.cleo.io.inputs.argument import Argument
    from conda_lock._vendor.cleo.io.inputs.option import Option


class NewCommand(InitCommand):
    name = "new"
    description = "Creates a new Python project at <path>."

    arguments: ClassVar[list[Argument]] = [
        argument("path", "The path to create the project at.")
    ]
    options: ClassVar[list[Option]] = [
        option(
            "interactive",
            "i",
            "Allow interactive specification of project configuration.",
            flag=True,
        ),
        option("name", None, "Set the resulting package name.", flag=False),
        option("src", None, "Use the src layout for the project."),
        option(
            "readme",
            None,
            "Specify the readme file format. Default is md.",
            flag=False,
        ),
        *[
            o
            for o in InitCommand.options
            if o.name
            in {
                "description",
                "author",
                "python",
                "dependency",
                "dev-dependency",
                "license",
            }
        ],
    ]

    def handle(self) -> int:
        from pathlib import Path

        if self.io.input.option("project"):
            self.line_error(
                "<warning>--project only makes sense with existing projects, and will"
                " be ignored. You should consider the option --path instead.</warning>"
            )

        path = Path(self.argument("path"))
        if not path.is_absolute():
            # we do not use resolve here due to compatibility issues
            # for path.resolve(strict=False)
            path = Path.cwd().joinpath(path)

        if path.exists() and list(path.glob("*")):
            # Directory is not empty. Aborting.
            raise RuntimeError(
                f"Destination <fg=yellow>{path}</> exists and is not empty"
            )

        return self._init_pyproject(
            project_path=path,
            allow_interactive=self.option("interactive"),
            layout_name="src" if self.option("src") else "standard",
            readme_format=self.option("readme") or "md",
        )
