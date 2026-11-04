#!/usr/bin/env python3
"""Run a command under a bounded filesystem capture on the authorized CI fork."""

import argparse
import collections
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
    parser.add_argument("--launch-windows", action="store_true")
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
        "window_lines": 0,
        "launch_windows": 0,
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
        "-e",
        str(os.getpid()),
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
            recent = collections.deque(maxlen=100000)
            last_written = -1
            until = -1.0
            with (
                (args.output / "events.jsonl").open("w", buffering=1) as events,
                (args.output / "windows.jsonl").open("w") as windows,
            ):
                for line in trace.stdout:
                    stats["input_lines"] += 1
                    fields = line.split()
                    if args.launch_windows and len(fields) > 2:
                        try:
                            h, m, s = fields[0].split(":")
                            stamp = int(h) * 3600 + int(m) * 60 + float(s)
                        except ValueError:
                            stamp = None
                        if stamp is not None:
                            row = (stats["input_lines"], stamp, line.rstrip("\n"))
                            recent.append(row)
                            while recent and recent[0][1] < stamp - 2:
                                recent.popleft()
                            launch = (
                                fields[1] in {"execve", "posix_spawn"}
                                and "/bin/gdalinfo " in line
                            )
                            if launch:
                                stats["launch_windows"] += 1
                                until = stamp + 1
                            if stamp <= until:
                                for seq, _, raw in recent if launch else [row]:
                                    if seq > last_written:
                                        windows.write(
                                            json.dumps({"sequence": seq, "line": raw})
                                            + "\n"
                                        )
                                        stats["window_lines"] += 1
                                        last_written = seq
                    if not ready.is_set():
                        stats["first_input_ns"] = time.time_ns()
                        ready.set()
                    # Metadata calls on directory descriptors may omit a pathname.
                    actor = fields[-1].rsplit(".", 1)[0] if fields else ""
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
