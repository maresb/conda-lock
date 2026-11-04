"""Generate isolated benchmarks from the unchanged workflows at b32d4e58."""

import copy
import json
import re

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
BRANCH = "experiment/ci-performance-20261104"


class Loader(yaml.SafeLoader):
    pass


Loader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in Loader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)


def load(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=Loader)


def string_input():
    return {"required": True, "type": "string"}


def save(name, data):
    class Dumper(yaml.SafeDumper):
        pass

    def represent_string(dumper, value):
        return dumper.represent_scalar(
            "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
        )

    Dumper.add_representer(str, represent_string)
    (WORKFLOWS / name).write_text(
        yaml.dump(data, Dumper=Dumper, sort_keys=False, width=120)
    )


def reusable(source, name, inputs=None):
    result = copy.deepcopy(source)
    result["name"] = name
    result["on"] = {"workflow_call": {"inputs": inputs or {}}}
    result.pop("concurrency", None)
    for job in result["jobs"].values():
        job["timeout-minutes"] = 25
    return result


def replace_matrix(value):
    if isinstance(value, str):
        return value.replace("matrix.os", "inputs.os").replace(
            "matrix.python-version", "inputs.python-version"
        )
    if isinstance(value, dict):
        return {key: replace_matrix(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_matrix(item) for item in value]
    return value


def disable_conda_cleanup(job):
    for step in job.get("steps", []):
        if step.get("uses", "").startswith("conda-incubator/setup-miniconda@"):
            step.setdefault("with", {})["run-post"] = False


def matrix(mac_shards, windows_shards):
    return json.dumps(
        {
            "include": [
                {
                    "os": os,
                    "python-version": py,
                    "pytest-split-group-index": group,
                    "pytest-split-group-size": count,
                }
                for os, count in [
                    ("ubuntu-latest", 3),
                    ("macos-latest", mac_shards),
                    ("windows-latest", windows_shards),
                ]
                for py in ["3.11", "3.14"]
                for group in range(1, count + 1)
            ]
        }
    )


unit = reusable(
    load("test.yml"),
    "Benchmark pytest",
    {"matrix": string_input(), "cache-group": string_input()},
)
test = unit["jobs"]["test"]
test["strategy"]["matrix"] = "${{ fromJSON(inputs.matrix) }}"
variables = {
    "matrix.os": "PYTEST_OS",
    "matrix.python-version": "PYTEST_PYTHON",
    "matrix.pytest-split-group-size": "PYTEST_SPLITS",
    "matrix.pytest-split-group-index": "PYTEST_GROUP",
}
test["env"].update(
    {
        variable: "${{ " + expression + " }}"
        for expression, variable in variables.items()
    }
)
test["steps"] = [
    step for step in test["steps"] if not step.get("uses", "").startswith("codecov/")
]
for step in test["steps"]:
    if "run" in step:
        for expression, variable in variables.items():
            step["run"] = step["run"].replace(
                "${{ " + expression + " }}", "${" + variable + "}"
            )
    if step.get("uses", "").startswith("mamba-org/setup-micromamba@"):
        step["with"]["cache-environment-key"] = (
            "ci-perf-20261104-${{ inputs.cache-group }}-${{ matrix.os }}-py${{ matrix.python-version }}"
        )
save("ci-perf-pytest.yml", unit)

integration = load("integration-test.yml")
baseline = reusable(integration, "Benchmark original integration")
save("ci-perf-integration-baseline.yml", baseline)

pipeline = reusable(
    integration,
    "Benchmark independent integration pipeline",
    {
        "os": string_input(),
        "python-version": string_input(),
    },
)
pipeline["jobs"] = {}
for key in [
    "lock-gdal",
    "install-gdal-with-micromamba",
    "install-gdal-with-conda",
    "install-gdal-with-conda-lock",
]:
    job = replace_matrix(copy.deepcopy(integration["jobs"][key]))
    job.pop("strategy")
    job["timeout-minutes"] = 25
    disable_conda_cleanup(job)
    if key in ["install-gdal-with-micromamba", "install-gdal-with-conda"]:
        job["if"] = "inputs.python-version == '3.11'"
    if key == "install-gdal-with-conda-lock":
        job["strategy"] = {
            "fail-fast": False,
            "matrix": {
                "format": '${{ fromJSON(inputs.os == \'windows-latest\' && \'["lock","explicit","env"]\' || \'["all"]\') }}'
            },
        }
        job["name"] = "conda-lock install (${{ matrix.format }})"
        for step in job["steps"]:
            if step.get("name") == "Install GDAL with conda-lock":
                step["env"] = {"LOCK_FORMAT": "${{ matrix.format }}"}
                step["run"] = """for format in lock explicit env; do
  if [[ "$LOCK_FORMAT" != all && "$LOCK_FORMAT" != "$format" ]]; then
    continue
  fi
  case "$format" in
    lock) lockfiles=(lockfiles/conda-lock.yml) ;;
    explicit) lockfiles=(lockfiles/conda-*.lock) ;;
    env) lockfiles=(lockfiles/conda-*.lock.yml) ;;
  esac
  conda-lock install --log-level=DEBUG -n "gdal-test-cl-$format" "${lockfiles[@]}"
  conda list -n "gdal-test-cl-$format"
  conda run -n "gdal-test-cl-$format" gdalinfo --version
  conda run -n "gdal-test-cl-$format" python -c 'import toolz; print(toolz.__version__)'
done
"""
    pipeline["jobs"][key] = job
save("ci-perf-integration-pipeline.yml", pipeline)

candidate = reusable(integration, "Benchmark candidate integration")
plugin_job = copy.deepcopy(candidate["jobs"]["lock-gdal-via-conda"])
disable_conda_cleanup(plugin_job)
candidate["jobs"] = {
    "platform": {
        "strategy": {
            "fail-fast": False,
            "matrix": {
                "os": ["ubuntu-latest", "macos-latest", "windows-latest"],
                "python-version": ["3.11", "3.14"],
            },
        },
        "uses": "./.github/workflows/ci-perf-integration-pipeline.yml",
        "permissions": {"contents": "read", "actions": "write"},
        "with": {
            "os": "${{ matrix.os }}",
            "python-version": "${{ matrix.python-version }}",
        },
    },
    "lock-gdal-via-conda": plugin_job,
    "integration-test-status": copy.deepcopy(
        candidate["jobs"]["integration-test-status"]
    ),
}
candidate["jobs"]["integration-test-status"]["needs"] = [
    "platform",
    "lock-gdal-via-conda",
]
save("ci-perf-integration-candidate.yml", candidate)

checkout = copy.deepcopy(test["steps"][0])
top = {
    "name": "CI performance experiment",
    "on": {"push": {"branches": [BRANCH]}},
    "permissions": {},
    "concurrency": {
        "group": "ci-performance-${{ github.sha }}",
        "cancel-in-progress": False,
    },
    "jobs": {
        "configure": {
            "if": "github.repository == 'maresb/conda-lock'",
            "runs-on": "ubuntu-slim",
            "timeout-minutes": 5,
            "permissions": {"contents": "read"},
            "outputs": {
                "mode": "${{ steps.case.outputs.mode }}",
                "repeat": "${{ steps.case.outputs.repeat }}",
            },
            "steps": [
                checkout,
                {
                    "id": "case",
                    "run": 'cat experiments/ci-performance/case.env >> "$GITHUB_OUTPUT"',
                },
            ],
        },
    },
}
for mode, shards in [("baseline", 10), ("candidate", 4)]:
    condition = f"needs.configure.outputs.mode == '{mode}'"
    top["jobs"][f"{mode}-pytest"] = {
        "permissions": {"contents": "read", "actions": "write"},
        "needs": "configure",
        "if": condition,
        "uses": "./.github/workflows/ci-perf-pytest.yml",
        "with": {"matrix": matrix(shards, shards), "cache-group": mode},
    }
    top["jobs"][f"{mode}-integration"] = {
        "permissions": {"contents": "read", "actions": "write"},
        "needs": "configure",
        "if": condition,
        "uses": f"./.github/workflows/ci-perf-integration-{mode}.yml",
    }
save("ci-performance-experiment.yml", top)
