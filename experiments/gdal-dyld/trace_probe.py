#!/usr/bin/env python3
"""Run a command under a bounded filesystem capture on the authorized CI fork."""

import argparse
import datetime
import json
import os
import subprocess
import sys
import threading
import time

from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != "maresb/conda-lock"
    ):
        parser.error(
            "This capture is restricted to GitHub Actions on maresb/conda-lock"
        )
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout < 1:
        parser.error("Supply a command and positive timeout")
    args.output.mkdir(parents=True, exist_ok=False)
    ready = threading.Event()
    stats = {
        "started_ns": time.time_ns(),
        "timezone": str(datetime.datetime.now().astimezone().tzinfo),
        "input_lines": 0,
        "retained_lines": 0,
        "command": command,
    }
    trace_command = [
        "sudo",
        "-n",
        "/usr/bin/fs_usage",
        "-w",
        "-f",
        "filesys",
        "-f",
        "exec",
        "-t",
        str(args.timeout),
    ]
    stats["trace_command"] = trace_command
    returncode = 1
    with (args.output / "stderr.log").open("w") as errors:
        trace = subprocess.Popen(
            trace_command,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            start_new_session=True,
        )

        def collect():
            assert trace.stdout is not None
            with (args.output / "events.jsonl").open("w", buffering=1) as events:
                for line in trace.stdout:
                    stats["input_lines"] += 1
                    if not ready.is_set():
                        stats["first_input_ns"] = time.time_ns()
                        ready.set()
                    # Metadata calls on directory descriptors may omit a pathname.
                    actor = line.split()[-1].rsplit(".", 1)[0] if line.split() else ""
                    context_actor = actor.startswith(
                        ("mdworker", "mds", "mdimport")
                    ) or actor in {
                        "fseventsd",
                        "amfid",
                        "syspolicyd",
                        "metadata_reader",
                        "ReportCrash",
                        "osanalyticshelper",
                    }
                    if "gdalinfo" in line or "libgdal" in line or context_actor:
                        events.write(
                            json.dumps(
                                {
                                    "received_ns": time.time_ns(),
                                    "line": line.rstrip("\n"),
                                }
                            )
                            + "\n"
                        )
                        stats["retained_lines"] += 1

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        try:
            if not ready.wait(15) or trace.poll() is not None:
                raise RuntimeError("fs_usage did not start; inspect trace/stderr.log")
            stats["command_started_ns"] = time.time_ns()
            returncode = subprocess.run(
                command, timeout=args.timeout - 20, check=False
            ).returncode
            stats["command_ended_ns"] = time.time_ns()
            stats["trace_alive_at_command_end"] = trace.poll() is None
        finally:
            if trace.poll() is None:
                subprocess.run(
                    [
                        "sudo",
                        "-n",
                        "/usr/bin/python3",
                        "-c",
                        "import os,signal,sys\ntry: os.killpg(int(sys.argv[1]), signal.SIGINT)\nexcept ProcessLookupError: pass",
                        str(trace.pid),
                    ],
                    check=True,
                )
            trace.wait(timeout=15)
            thread.join(timeout=10)
            stats["trace_returncode"] = trace.returncode
            stats["command_returncode"] = returncode
            stats["ended_ns"] = time.time_ns()
            (args.output / "summary.json").write_text(
                json.dumps(stats, indent=2) + "\n"
            )
    if not stats.get("trace_alive_at_command_end") or not stats["retained_lines"]:
        raise RuntimeError(
            "Incomplete filesystem capture; inspect retained diagnostics"
        )
    return returncode


if __name__ == "__main__":
    sys.exit(main())
