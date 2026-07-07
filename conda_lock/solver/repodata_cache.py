"""Local package-cache I/O for the conda-lock dryrun pipeline.

This module owns the question "what does the on-disk cache say about a
given distribution?" -- nothing else.
"""

import json
import logging
import pathlib
import time

from conda_lock.models.dry_run_install import FetchAction


logger = logging.getLogger(__name__)


def get_repodata_record(
    pkgs_dirs: list[pathlib.Path], dist_name: str
) -> FetchAction | None:
    """Get the repodata_record.json of a given distribution from the package cache.

    On rare occasion during the CI tests, conda fails to find a package in the
    package cache, perhaps because the package is still being processed? Waiting for
    0.1 seconds seems to solve the issue. Here we allow for a full second to elapse
    before giving up.
    """
    NUM_RETRIES = 10
    for retry in range(1, NUM_RETRIES + 1):
        for pkgs_dir in pkgs_dirs:
            record = pkgs_dir / dist_name / "info" / "repodata_record.json"
            if record.exists():
                with open(record) as f:
                    repodata: FetchAction = json.load(f)
                return repodata
        logger.warning(
            f"Failed to find repodata_record.json for {dist_name}. "
            f"Retrying in 0.1 seconds ({retry}/{NUM_RETRIES})"
        )
        time.sleep(0.1)
    logger.warning(f"Failed to find repodata_record.json for {dist_name}. Giving up.")
    return None
