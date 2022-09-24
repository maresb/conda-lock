import shlex
import subprocess

from functools import cache


def run_command(command: str | list[str]) -> str:
    try:
        if isinstance(command, str):
            command = shlex.split(command)
        output = subprocess.check_output(command)
    except subprocess.CalledProcessError as e:
        print(f"Error when running command: {command}")
        print(e.output.decode())
        raise
    return output.decode()


def get_commit_messages() -> dict[str, str]:
    command = "git log --reverse --format=%H%n%B%n%n--next--%n%n"
    output = run_command(command)
    split_output = output.split("\n\n--next--\n\n\n")
    shas_and_messages = {
        commit_hash: commit_message.strip()
        for commit_hash, commit_message in [
            commit_output.split("\n", maxsplit=1)
            for commit_output in split_output
            if commit_output != ""
        ]
    }
    return shas_and_messages


def is_repo_clean() -> bool:
    command = "git status --porcelain"
    output = run_command(command)
    return output == ""


def add_and_commit(message: str) -> None:
    command = "git add --all"
    run_command(command)
    command = ["git", "commit", "-m", message]
    run_command(command)


def get_current_sha() -> str:
    command = "git rev-parse HEAD"
    output = run_command(command)
    return output.strip()


def reset_latest_commit() -> None:
    command = "git reset --hard HEAD^"
    run_command(command)
