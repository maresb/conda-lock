"""Add isolated resource measurements to generated benchmark workflows."""

import copy
import json

import generate as generator


PYTHON_ACTION = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
UPLOAD_ACTION = "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f"
SCRIPT = "experiments/ci-performance/telemetry.py"
COMMAND = f'"$MONITOR_PY" {SCRIPT}'
START = {
    "name": "Start resource sampler",
    "id": "metrics",
    "shell": "bash -eo pipefail {0}",
    "run": f"""python -m venv "$RUNNER_TEMP/ci-metrics-venv"
if [[ "$RUNNER_OS" == Windows ]]; then
  metrics_python="$RUNNER_TEMP/ci-metrics-venv/Scripts/python.exe"
else
  metrics_python="$RUNNER_TEMP/ci-metrics-venv/bin/python"
fi
"$metrics_python" -m pip install --disable-pip-version-check psutil==7.1.0
echo "MONITOR_PY=$metrics_python" >> "$GITHUB_ENV"
"$metrics_python" {SCRIPT} start
""",
}
UPLOAD = {
    "name": "Upload resource measurements",
    "if": "always() && steps.metrics.outcome == 'success'",
    "uses": UPLOAD_ACTION,
    "with": {
        "name": "metrics-${{ env.METRICS_ID }}",
        "path": "${{ runner.temp }}/ci-metrics",
        "if-no-files-found": "error",
    },
}


def instrument(job):
    job.setdefault("env", {}).update(
        {
            "METRICS_MATRIX": "${{ toJSON(matrix) }}",
            "METRICS_INPUTS": "${{ toJSON(inputs) }}",
        }
    )
    steps = []
    started = False
    for step in job["steps"]:
        if started:
            label = step.get("name", step.get("uses", "step")).split("@")[0]
            steps.append(
                {
                    "name": "Measure " + label,
                    "shell": "bash -eo pipefail {0}",
                    "env": {"METRICS_PHASE": label},
                    "run": f'{COMMAND} mark --label "$METRICS_PHASE"',
                }
            )
        steps.append(step)
        if step.get("uses", "").startswith("actions/checkout@"):
            steps.extend(
                [
                    {
                        "name": "Set up telemetry Python",
                        "uses": PYTHON_ACTION,
                        "with": {"python-version": "3.11"},
                    },
                    copy.deepcopy(START),
                ]
            )
            started = True
    assert started, "Instrumented jobs must check out the sampler"
    steps.extend(
        [
            {
                "name": "Stop resource sampler",
                "if": "always() && steps.metrics.outcome == 'success'",
                "shell": "bash -eo pipefail {0}",
                "run": f"{COMMAND} stop",
            },
            copy.deepcopy(UPLOAD),
        ]
    )
    job["steps"] = steps


unit = generator.load("ci-perf-pytest.yml")
unit["jobs"]["test"]["env"]["PYTEST_WORKERS"] = "${{ matrix.pytest-workers || 'auto' }}"
for step in unit["jobs"]["test"]["steps"]:
    if step.get("name") == "run-test":
        step["run"] = step["run"].replace(
            "pytest \\\n", 'pytest --numprocesses="$PYTEST_WORKERS" \\\n'
        )
instrument(unit["jobs"]["test"])
for step in unit["jobs"]["aggregate-durations"]["steps"]:
    if step.get("uses", "").startswith("actions/download-artifact@"):
        step["with"] = {"pattern": "test-durations-*"}
generator.save("ci-perf-pytest.yml", unit)

windows = generator.load("ci-perf-windows-control.yml")
local_concurrency = copy.deepcopy(windows["jobs"]["parallel"])
local_concurrency.pop("needs")
local_concurrency["name"] = "Three formats on one runner (${{ matrix.repeat }})"
local_concurrency["strategy"]["matrix"] = {"repeat": [1, 2]}
for step in local_concurrency["steps"]:
    if step.get("name") == "Download lockfiles":
        step["with"].update(
            {"run-id": 41885415752, "github-token": "${{ github.token }}"}
        )
    if step.get("name") == "Install GDAL with conda-lock":
        original = step["run"]
        step.pop("env", None)
        step["run"] = (
            """pids=()
for format_to_run in lock explicit env; do
  (
    export LOCK_FORMAT="$format_to_run"
    export CONDA_PKGS_DIRS="$RUNNER_TEMP/format-pkgs-$format_to_run"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
"""
            + original
            + """
    date -u '+%Y-%m-%dT%H:%M:%SZ'
  ) > "$RUNNER_TEMP/install-$format_to_run.log" 2>&1 &
  pids+=("$!")
done
result=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then result=1; fi
done
for format_to_run in lock explicit env; do
  echo "Format: $format_to_run"
  cat "$RUNNER_TEMP/install-$format_to_run.log"
done
exit "$result"
"""
        )
instrument(local_concurrency)
generator.save(
    "ci-perf-local-concurrency.yml",
    {
        "name": "Measure concurrent formats on one Windows runner",
        "on": {"workflow_call": {}},
        "permissions": {},
        "defaults": windows["defaults"],
        "jobs": {"local-concurrency": local_concurrency},
    },
)
for job in windows["jobs"].values():
    instrument(job)
generator.save("ci-perf-windows-control.yml", windows)

top = generator.load("ci-performance-experiment.yml")
top["jobs"]["windows-local-concurrency"] = {
    "needs": "configure",
    "if": "needs.configure.outputs.mode == 'windows-local-concurrency'",
    "permissions": {"contents": "read", "actions": "read"},
    "uses": "./.github/workflows/ci-perf-local-concurrency.yml",
}
top["jobs"]["cpu-probe"] = {
    "needs": "configure",
    "if": "needs.configure.outputs.mode == 'cpu-probe'",
    "runs-on": "${{ matrix.os }}",
    "permissions": {"contents": "read"},
    "timeout-minutes": 5,
    "strategy": {
        "fail-fast": False,
        "matrix": {"os": ["ubuntu-latest", "windows-latest", "macos-latest"]},
    },
    "steps": [
        copy.deepcopy(generator.checkout),
        {
            "name": "Known CPU load",
            "shell": "bash -eo pipefail {0}",
            "run": f"{COMMAND} calibrate",
        },
    ],
}
instrument(top["jobs"]["cpu-probe"])
# The calibration stops the recorder before checking the captured samples.
top["jobs"]["cpu-probe"]["steps"] = [
    step
    for step in top["jobs"]["cpu-probe"]["steps"]
    if step.get("name") != "Stop resource sampler"
]
linux_entries = [
    entry
    for entry in json.loads(generator.matrix(10, 10))["include"]
    if entry["os"] == "ubuntu-latest"
]
top["jobs"]["linux-pytest"] = {
    "needs": "configure",
    "if": "needs.configure.outputs.mode == 'windows-control'",
    "permissions": {"contents": "read", "actions": "write"},
    "uses": "./.github/workflows/ci-perf-pytest.yml",
    "with": {
        "matrix": json.dumps({"include": linux_entries}),
        "cache-group": "baseline",
    },
}
for platform, label, shards, cache_group in [
    ("linux", "ubuntu-latest", 3, "baseline"),
    ("windows", "windows-latest", 4, "candidate"),
]:
    entries = [
        entry
        for entry in json.loads(generator.matrix(shards, shards))["include"]
        if entry["os"] == label
    ]
    for entry in entries:
        entry["pytest-workers"] = "4"
    case = platform + "-workers4"
    top["jobs"][case] = {
        "needs": "configure",
        "if": f"needs.configure.outputs.mode == '{case}'",
        "permissions": {"contents": "read", "actions": "write"},
        "uses": "./.github/workflows/ci-perf-pytest.yml",
        "with": {
            "matrix": json.dumps({"include": entries}),
            "cache-group": cache_group,
        },
    }
generator.save("ci-performance-experiment.yml", top)
