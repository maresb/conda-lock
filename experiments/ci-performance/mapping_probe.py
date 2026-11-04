"""Observe mapping-cache waits without changing the cache or HTTP implementation."""

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
import time

from pathlib import Path


_stream = None
_mutex = threading.Lock()
_current_test = None


def emit(event, **fields):
    if _stream is None:
        return
    row = {
        "time": time.time(),
        "monotonic": time.monotonic(),
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "worker": os.environ.get("PYTEST_XDIST_WORKER", "controller"),
        "test": _current_test,
        "event": event,
        **fields,
    }
    with _mutex:
        _stream.write(json.dumps(row) + "\n")
        _stream.flush()


class CacheEvents(logging.Handler):
    def emit(self, record):
        emit(
            "cache",
            logger=record.name,
            level=record.levelname,
            message=record.getMessage(),
        )


def observe(directory, label):
    global _stream
    directory.mkdir(parents=True, exist_ok=True)
    _stream = (directory / f"mapping-{label}-{os.getpid()}.jsonl").open("a")
    handler = CacheEvents()
    for name in ["conda_lock.lookup", "conda_lock.lookup_cache"]:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    emit("observer-start")


def pytest_configure(config):
    observe(
        Path(os.environ["MAPPING_TRACE_DIR"]),
        os.environ.get("PYTEST_XDIST_WORKER", "controller"),
    )


def pytest_runtest_logstart(nodeid, location):
    global _current_test
    _current_test = nodeid
    emit("test-start")


def pytest_runtest_logreport(report):
    emit(
        "test-report",
        nodeid=report.nodeid,
        when=report.when,
        duration=report.duration,
        outcome=report.outcome,
        start=report.start,
        stop=report.stop,
    )


def prepare(state):
    from conda_lock.lookup import DEFAULT_MAPPING_URL, _get_pypi_lookup
    from conda_lock.lookup_cache import cached_filename_for_url, user_cache_path

    observe(Path(os.environ["MAPPING_TRACE_DIR"]), "prepare")
    started = time.monotonic()
    cache = user_cache_path("conda-lock", appauthor=False) / "cache" / "pypi-mapping"
    destination = cache / cached_filename_for_url(DEFAULT_MAPPING_URL)
    # A fresh hosted runner is expected; never erase a pre-existing user's cache.
    if destination.exists():
        raise RuntimeError(f"Expected a cold mapping cache; found {destination}")
    emit("prepare-start", state=state)
    if state == "primed":
        lookup = _get_pypi_lookup(DEFAULT_MAPPING_URL)
        emit(
            "mapping-primed",
            entries=len(lookup),
            bytes=destination.stat().st_size,
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        )
    emit("prepare-finish", state=state, elapsed=time.monotonic() - started)


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "pytest"])
    parser.add_argument("--state", choices=["cold", "primed"])
    args, pytest_args = parser.parse_known_args()
    if args.command == "prepare":
        if args.state is None:
            parser.error("prepare requires --state")
        prepare(args.state)
    else:
        import pytest

        raise SystemExit(pytest.main(["-p", "mapping_probe", *pytest_args]))


if __name__ == "__main__":
    main()
