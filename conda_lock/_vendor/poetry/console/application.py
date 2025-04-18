from __future__ import annotations

import logging
import re

from contextlib import suppress
from functools import cached_property
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast

from conda_lock._vendor.cleo.application import Application as BaseApplication
from conda_lock._vendor.cleo.events.console_command_event import ConsoleCommandEvent
from conda_lock._vendor.cleo.events.console_events import COMMAND
from conda_lock._vendor.cleo.events.event_dispatcher import EventDispatcher
from conda_lock._vendor.cleo.exceptions import CleoError
from conda_lock._vendor.cleo.formatters.style import Style

from conda_lock._vendor.poetry.__version__ import __version__
from conda_lock._vendor.poetry.console.command_loader import CommandLoader
from conda_lock._vendor.poetry.console.commands.command import Command
from conda_lock._vendor.poetry.utils.helpers import directory


if TYPE_CHECKING:
    from collections.abc import Callable

    from conda_lock._vendor.cleo.events.event import Event
    from conda_lock._vendor.cleo.io.inputs.argv_input import ArgvInput
    from conda_lock._vendor.cleo.io.inputs.definition import Definition
    from conda_lock._vendor.cleo.io.inputs.input import Input
    from conda_lock._vendor.cleo.io.io import IO
    from conda_lock._vendor.cleo.io.outputs.output import Output

    from conda_lock._vendor.poetry.console.commands.installer_command import InstallerCommand
    from conda_lock._vendor.poetry.poetry import Poetry


def load_command(name: str) -> Callable[[], Command]:
    def _load() -> Command:
        words = name.split(" ")
        module = import_module("poetry.console.commands." + ".".join(words))
        command_class = getattr(module, "".join(c.title() for c in words) + "Command")
        command: Command = command_class()
        return command

    return _load


COMMANDS = [
    "about",
    "add",
    "build",
    "check",
    "config",
    "init",
    "install",
    "lock",
    "new",
    "publish",
    "remove",
    "run",
    "search",
    "show",
    "sync",
    "update",
    "version",
    # Cache commands
    "cache clear",
    "cache list",
    # Debug commands
    "debug info",
    "debug resolve",
    # Env commands
    "env activate",
    "env info",
    "env list",
    "env remove",
    "env use",
    # Self commands
    "self add",
    "self install",
    "self lock",
    "self remove",
    "self update",
    "self show",
    "self show plugins",
    "self sync",
    # Source commands
    "source add",
    "source remove",
    "source show",
]


class Application(BaseApplication):
    def __init__(self) -> None:
        super().__init__("poetry", __version__)

        self._poetry: Poetry | None = None
        self._io: IO | None = None
        self._disable_plugins = False
        self._disable_cache = False
        self._plugins_loaded = False

        dispatcher = EventDispatcher()
        dispatcher.add_listener(COMMAND, self.register_command_loggers)
        dispatcher.add_listener(COMMAND, self.configure_env)
        dispatcher.add_listener(COMMAND, self.configure_installer_for_event)
        self.set_event_dispatcher(dispatcher)

        command_loader = CommandLoader({name: load_command(name) for name in COMMANDS})
        self.set_command_loader(command_loader)

    @property
    def _default_definition(self) -> Definition:
        from conda_lock._vendor.cleo.io.inputs.option import Option

        definition = super()._default_definition

        definition.add_option(
            Option("--no-plugins", flag=True, description="Disables plugins.")
        )

        definition.add_option(
            Option(
                "--no-cache", flag=True, description="Disables Poetry source caches."
            )
        )

        definition.add_option(
            Option(
                "--project",
                "-P",
                flag=False,
                description=(
                    "Specify another path as the project root."
                    " All command-line arguments will be resolved relative to the current working directory."
                ),
            )
        )

        definition.add_option(
            Option(
                "--directory",
                "-C",
                flag=False,
                description=(
                    "The working directory for the Poetry command (defaults to the"
                    " current working directory). All command-line arguments will be"
                    " resolved relative to the given directory."
                ),
            )
        )

        return definition

    @cached_property
    def _project_directory(self) -> Path:
        if self._io and self._io.input.option("project"):
            with directory(self._working_directory):
                return Path(self._io.input.option("project")).absolute()

        return self._working_directory

    @cached_property
    def _working_directory(self) -> Path:
        if self._io and self._io.input.option("directory"):
            return Path(self._io.input.option("directory")).absolute()

        return Path.cwd()

    @property
    def poetry(self) -> Poetry:
        from conda_lock._vendor.poetry.factory import Factory

        if self._poetry is not None:
            return self._poetry

        self._poetry = Factory().create_poetry(
            cwd=self._project_directory,
            io=self._io,
            disable_plugins=self._disable_plugins,
            disable_cache=self._disable_cache,
        )

        return self._poetry

    @property
    def command_loader(self) -> CommandLoader:
        command_loader = self._command_loader
        assert isinstance(command_loader, CommandLoader)
        return command_loader

    def reset_poetry(self) -> None:
        self._poetry = None

    def create_io(
        self,
        input: Input | None = None,
        output: Output | None = None,
        error_output: Output | None = None,
    ) -> IO:
        io = super().create_io(input, output, error_output)

        # Set our own CLI styles
        formatter = io.output.formatter
        formatter.set_style("c1", Style("cyan"))
        formatter.set_style("c2", Style("default", options=["bold"]))
        formatter.set_style("info", Style("blue"))
        formatter.set_style("comment", Style("green"))
        formatter.set_style("warning", Style("yellow"))
        formatter.set_style("debug", Style("default", options=["dark"]))
        formatter.set_style("success", Style("green"))

        # Dark variants
        formatter.set_style("c1_dark", Style("cyan", options=["dark"]))
        formatter.set_style("c2_dark", Style("default", options=["bold", "dark"]))
        formatter.set_style("success_dark", Style("green", options=["dark"]))

        io.output.set_formatter(formatter)
        io.error_output.set_formatter(formatter)

        self._io = io

        return io

    def _run(self, io: IO) -> int:
        self._disable_plugins = io.input.parameter_option("--no-plugins")
        self._disable_cache = io.input.has_parameter_option("--no-cache")

        self._load_plugins(io)

        with directory(self._working_directory):
            exit_code: int = super()._run(io)

        return exit_code

    def _configure_io(self, io: IO) -> None:
        # We need to check if the command being run
        # is the "run" command.
        definition = self.definition
        with suppress(CleoError):
            io.input.bind(definition)

        name = io.input.first_argument
        if name == "run":
            from conda_lock._vendor.poetry.console.io.inputs.run_argv_input import RunArgvInput

            input = cast("ArgvInput", io.input)
            run_input = RunArgvInput([self._name or "", *input._tokens])
            # For the run command reset the definition
            # with only the set options (i.e. the options given before the command)
            for option_name, value in input.options.items():
                if value:
                    option = definition.option(option_name)
                    run_input.add_parameter_option("--" + option.name)
                    if option.shortcut:
                        shortcuts = re.split(r"\|-?", option.shortcut.lstrip("-"))
                        shortcuts = [s for s in shortcuts if s]
                        for shortcut in shortcuts:
                            run_input.add_parameter_option("-" + shortcut.lstrip("-"))

            with suppress(CleoError):
                run_input.bind(definition)

            for option_name, value in input.options.items():
                if value:
                    run_input.set_option(option_name, value)

            io.set_input(run_input)

        super()._configure_io(io)

    def register_command_loggers(
        self, event: Event, event_name: str, _: EventDispatcher
    ) -> None:
        from conda_lock._vendor.poetry.console.logging.filters import POETRY_FILTER
        from conda_lock._vendor.poetry.console.logging.io_formatter import IOFormatter
        from conda_lock._vendor.poetry.console.logging.io_handler import IOHandler

        assert isinstance(event, ConsoleCommandEvent)
        command = event.command
        if not isinstance(command, Command):
            return

        io = event.io

        loggers = [
            "poetry.packages.locker",
            "poetry.packages.package",
            "poetry.utils.password_manager",
        ]

        loggers += command.loggers

        handler = IOHandler(io)
        handler.setFormatter(IOFormatter())

        level = logging.WARNING

        if io.is_debug():
            level = logging.DEBUG
        elif io.is_very_verbose() or io.is_verbose():
            level = logging.INFO

        logging.basicConfig(level=level, handlers=[handler])

        # only log third-party packages when very verbose
        if not io.is_very_verbose():
            handler.addFilter(POETRY_FILTER)

        for name in loggers:
            logger = logging.getLogger(name)

            _level = level
            # The builders loggers are special and we can actually
            # start at the INFO level.
            if (
                logger.name.startswith("poetry.core.masonry.builders")
                and _level > logging.INFO
            ):
                _level = logging.INFO

            logger.setLevel(_level)

    def configure_env(self, event: Event, event_name: str, _: EventDispatcher) -> None:
        from conda_lock._vendor.poetry.console.commands.env_command import EnvCommand
        from conda_lock._vendor.poetry.console.commands.self.self_command import SelfCommand

        assert isinstance(event, ConsoleCommandEvent)
        command = event.command
        if not isinstance(command, EnvCommand) or isinstance(command, SelfCommand):
            return

        if command._env is not None:
            return

        from conda_lock._vendor.poetry.utils.env import EnvManager

        io = event.io
        poetry = command.poetry

        env_manager = EnvManager(poetry, io=io)
        env = env_manager.create_venv()

        if env.is_venv() and io.is_verbose():
            io.write_line(f"Using virtualenv: <comment>{env.path}</>")

        command.set_env(env)

    @classmethod
    def configure_installer_for_event(
        cls, event: Event, event_name: str, _: EventDispatcher
    ) -> None:
        from conda_lock._vendor.poetry.console.commands.installer_command import InstallerCommand

        assert isinstance(event, ConsoleCommandEvent)
        command = event.command
        if not isinstance(command, InstallerCommand):
            return

        # If the command already has an installer
        # we skip this step
        if command._installer is not None:
            return

        cls.configure_installer_for_command(command, event.io)

    @staticmethod
    def configure_installer_for_command(command: InstallerCommand, io: IO) -> None:
        from conda_lock._vendor.poetry.installation.installer import Installer

        poetry = command.poetry
        installer = Installer(
            io,
            command.env,
            poetry.package,
            poetry.locker,
            poetry.pool,
            poetry.config,
            disable_cache=poetry.disable_cache,
        )
        command.set_installer(installer)

    def _load_plugins(self, io: IO) -> None:
        if self._plugins_loaded:
            return

        self._disable_plugins = io.input.has_parameter_option("--no-plugins")

        if not self._disable_plugins:
            from conda_lock._vendor.poetry.plugins.application_plugin import ApplicationPlugin
            from conda_lock._vendor.poetry.plugins.plugin_manager import PluginManager

            PluginManager.add_project_plugin_path(self._project_directory)
            manager = PluginManager(ApplicationPlugin.group)
            manager.load_plugins()
            manager.activate(self)

        self._plugins_loaded = True


def main() -> int:
    exit_code: int = Application().run()
    return exit_code


if __name__ == "__main__":
    main()
