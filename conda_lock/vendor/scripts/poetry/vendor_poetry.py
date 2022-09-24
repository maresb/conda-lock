#!/usr/bin/env python3


import random
import shlex
import string
import subprocess

from pathlib import Path
from typing import Callable

import typer

from .migration_utils import get_latest_applied_stage, migration_stage, upgrade_to, reset_to


app = typer.Typer()


def str_to_stage(stage: str) -> tuple[int, ...]:
    if stage.lower == "none":
        return ()
    return tuple(int(x) for x in stage.split("."))


@migration_stage(stage=1, description="Add a migration")
def add_migration():
    asdf = Path("asdf")
    random_characters = "".join(random.choices(string.ascii_letters, k=10))
    asdf.write_text(random_characters)


@app.command()
def current():
    """Print the current version of the database"""
    latest_applied_stage = get_latest_applied_stage()
    typer.echo(f"Current stage: {latest_applied_stage}")


@app.command()
def upgrade(stage: str):
    """Upgrade to the given stage"""
    upgrade_to(str_to_stage(stage))


@app.command()
def reset(stage: str):
    """Reset to the given former stage"""
    reset_to(str_to_stage(stage))


if __name__ == "__main__":
    app()
