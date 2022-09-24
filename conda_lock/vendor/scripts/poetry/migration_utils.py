from functools import total_ordering
from typing import Callable

from pydantic import BaseModel

from .git_utils import (
    add_and_commit,
    get_commit_messages,
    get_current_sha,
    is_repo_clean,
    reset_latest_commit,
)


OriginalMigrationFunc = Callable[[], None]

MIGRATION_RECORD_DELIMITER = "\n\nvendor_poetry.py migration record:\n"


@total_ordering
class MigrationRecord(BaseModel):
    stage: tuple[int, ...]
    rev: tuple[int, ...]

    def __lt__(self, other):
        return self.stage < other.stage

    def __eq__(self, other):
        return self.stage == other.stage

    class Config:
        frozen = True

    def __str__(self):
        if self.stage == ():
            return "None"
        else:
            return ".".join(str(stage) for stage in self.stage)


class MigrationStage(MigrationRecord):
    description: str
    action: OriginalMigrationFunc

    def __call__(self):
        self.action()

    @property
    def record(self):
        return MigrationRecord(stage=self.stage, rev=self.rev)

    class Config:
        fields = {"action": {"exclude": True}}


stage_registry: list[MigrationStage] = []


def migration_stage(
    *,
    stage: int | str | tuple[int, ...],
    rev: int | str | tuple[int, ...] = (),
    description: str,
) -> Callable[[OriginalMigrationFunc], MigrationStage]:
    # Convert stage and rev into tuples
    if isinstance(stage, int):
        stage = (stage,)
    if isinstance(stage, str):
        stage = tuple(int(x) for x in stage.split("."))
    if isinstance(rev, int):
        rev = (rev,)
    if isinstance(rev, str):
        rev = tuple(int(x) for x in rev.split("."))

    def decorator(func: OriginalMigrationFunc) -> MigrationStage:
        migration = MigrationStage(
            stage=stage, rev=rev, description=description, action=func
        )
        stage_registry.append(migration)
        return migration

    return decorator


def get_migration_commits() -> dict[str, MigrationRecord]:
    shas_and_messages = get_commit_messages()
    migration_commits = {}
    for sha, message in shas_and_messages.items():
        if MIGRATION_RECORD_DELIMITER in message:
            _, record_raw = message.split(MIGRATION_RECORD_DELIMITER)
            record = MigrationRecord.parse_raw(record_raw)
            migration_commits[sha] = record
    return migration_commits


def get_applied_and_unapplied_stages() -> tuple[
    list[MigrationStage], list[MigrationStage]
]:

    # TODO: Handle reverted stages
    known_stages = [record.stage for record in stage_registry]
    if len(known_stages) != len(set(known_stages)):
        raise RuntimeError(f"Duplicate migration stages")

    sorted_registry = sorted(stage_registry)
    migration_commits = get_migration_commits()
    applied_stages: list[MigrationStage] = []
    for (sha, record), expected in zip(migration_commits.items(), sorted_registry):
        if record != expected:
            raise RuntimeError(
                f"Migration record mismatch for commit {sha}. "
                f"Expected {expected}, got {record}"
            )
        if record.rev != expected.rev:
            raise RuntimeError(
                f"Migration revision mismatch for commit {sha}. "
                f"Expected {expected.rev}, got {record.rev}."
            )
        applied_stages.append(expected)
    if len(migration_commits) > len(sorted_registry):
        sha, record = list(migration_commits.items())[len(sorted_registry)]
        raise RuntimeError(f"Unexpected migration record {record} in commit {sha}")
    unapplied_stages = sorted_registry[len(applied_stages) :]
    return applied_stages, unapplied_stages


def get_latest_applied_stage() -> MigrationRecord:
    applied_stages, _ = get_applied_and_unapplied_stages()
    if applied_stages:
        return applied_stages[-1]
    return MigrationRecord(stage=(), rev=())


def execute_migration_stage(migration_stage: MigrationStage):
    if not is_repo_clean():
        raise RuntimeError("Cannot execute migration when repo is dirty")
    applied_stages, _ = get_applied_and_unapplied_stages()
    if migration_stage.record in applied_stages:
        raise RuntimeError("Migration stage already applied")
    if migration_stage.record <= get_latest_applied_stage():
        raise RuntimeError(
            f"Cannot execute migration stage {migration_stage.record.stage} "
            f"not greater than the current stage {get_latest_applied_stage()}"
        )
    print(
        f"Running migration {migration_stage.stage}{migration_stage.rev or ''}: "
        f"{migration_stage.description}"
    )
    migration_stage()
    message = (
        f"{migration_stage.description}{MIGRATION_RECORD_DELIMITER}"
        f"{migration_stage.record.json()}"
    )
    add_and_commit(message)


def upgrade_to(stage: tuple[int, ...]) -> None:
    current_stage = get_latest_applied_stage()
    applied_stages, unapplied_stages = get_applied_and_unapplied_stages()
    if stage == current_stage.stage:
        return
    if stage < current_stage.stage:
        raise RuntimeError(
            f"Cannot update to stage {stage} when current stage is {current_stage.stage}"
        )
    if stage not in [s.stage for s in unapplied_stages]:
        raise RuntimeError(f"Cannot update to unknown stage {stage}")
    for migration_stage in unapplied_stages:
        if migration_stage.stage == stage:
            break
        execute_migration_stage(migration_stage)


def reset_to(stage: tuple[int, ...]) -> None:
    current_stage = get_latest_applied_stage()
    applied_stages, unapplied_stages = get_applied_and_unapplied_stages()
    if stage == current_stage.stage:
        return
    if stage > current_stage.stage:
        raise RuntimeError(
            f"Cannot reset to stage {stage} when current stage is {current_stage.stage}"
        )
    if stage not in [s.stage for s in applied_stages]:
        raise RuntimeError(f"Cannot reset to unknown stage {stage}")
    for migration_stage in reversed(applied_stages):
        if migration_stage.stage == stage:
            break
        reset_migration_stage(migration_stage)


def reset_migration_stage(migration_stage_to_revert: MigrationStage):
    current_sha = get_current_sha()
    migration_commits = get_migration_commits()
    if current_sha not in migration_commits:
        raise RuntimeError(
            f"Cannot reset migration stage {migration_stage_to_revert.record.stage} "
            f"when not on a migration commit"
        )
    migration_record_current_commit = migration_commits[current_sha]
    latest_applied_stage = get_latest_applied_stage()
    if latest_applied_stage != migration_stage_to_revert:
        raise RuntimeError(
            f"Cannot reset stage {migration_stage_to_revert.stage} when current "
            f"stage is {latest_applied_stage.stage}"
        )
    if not is_repo_clean():
        raise RuntimeError("Cannot execute migration when repo is dirty")
    print(
        f"Resetting migration {migration_stage_to_revert.stage}"
        f"{migration_stage_to_revert.rev or ''}: "
        f"{migration_stage_to_revert.description}"
    )
    reset_latest_commit()
