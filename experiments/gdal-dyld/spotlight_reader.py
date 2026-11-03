#!/usr/bin/env python3
"""Repeatedly request metadata import for one experiment file on the CI runner."""

import signal
import subprocess
import sys


stopped = False


def stop(signum, frame):
    global stopped
    stopped = True


signal.signal(signal.SIGTERM, stop)
operation, path, log_path = sys.argv[1:]
command = ["/usr/bin/mdimport", "-i" if operation == "import" else "-t", path]
count = 0
with open(log_path, "w") as log:
    while not stopped:
        subprocess.run(command, stdout=log, stderr=log, timeout=10, check=True)
        count += 1
        if count == 1:
            print("ready", flush=True)
print(count, flush=True)
