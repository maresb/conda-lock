"""Machinery for preparing the conda-lock metadata headers.

The main function to build the header is 'make_metadata_header()'.

The actual functions which define the header fields are in lockfile_metadata_fields.py.

Also included is some Click stuff for the "--metadata=..." command-line option, and
some stuff to configure the PyYAML output.
"""

import inspect
import sys

from functools import lru_cache
from typing import List, Optional

import click
import yaml

from conda_lock.lockfile_metadata_fields import (
    METADATA_FIELDS_LIST,
    METADATA_FIELDS_LIST_AS_STRING,
    LiteralStr,
    MetadataFields,
)
from conda_lock.src_parser import LockSpecification


STR_TAG = "tag:yaml.org,2002:str"
"""Tag corresponding to the YAML string type."""

# Click stuff
# -----------

# This value of "PREVIOUS" is a special value. At some point we probably want
# to switch default to the new structured header. For that, uncomment the stuff
# directly below.
DEFAULT_METADATA_TO_INCLUDE = ["previous"]


# DEFAULT_METADATA_TO_INCLUDE = ["about", "platform", "input_hash"]
# """Default fields when '--metadata=...' is not present."""

# # Validate DEFAULT_METADATA_TO_INCLUDE.
# _invalid_fields = set(DEFAULT_METADATA_TO_INCLUDE) - set(METADATA_FIELDS_LIST)
# if _invalid_fields:
#     raise ValueError(f"Default metadata values {_invalid_fields} are invalid.")


def validate_metadata_to_include(ctx, param, metadata_to_include) -> List[str]:
    """Convert the comma-separated string of metadata fields into a list.

    For use as a callback function with Click.
    """
    if metadata_to_include == "none":
        return []
    elif metadata_to_include == "all":
        return METADATA_FIELDS_LIST
    elif metadata_to_include == "previous":
        return ["PREVIOUS"]
    else:
        # Parse and validate that metadata_to_include is a comma-separated list of
        # metadata keys.
        selected = metadata_to_include.split(",")
        for key in selected:
            # Validate the keys.
            if key not in METADATA_FIELDS_LIST:
                raise click.BadParameter(
                    f"'{key}' does not correspond to a valid field. It must be one of "
                    f"{METADATA_FIELDS_LIST_AS_STRING}."
                )
        return selected


# Header generation
# -----------------


def make_metadata_header(
    spec: LockSpecification,
    metadata_to_include: List[str] = DEFAULT_METADATA_TO_INCLUDE,
    comment: Optional[str] = None,
):
    """Constructs a string of commented YAML for inclusion as a header in lockfiles."""

    if metadata_to_include == []:
        return ""

    if metadata_to_include == ["PREVIOUS"]:
        return _previous_metadata_header(spec)

    if comment and "comment" not in metadata_to_include:
        metadata_to_include.append("comment")

    fields = MetadataFields(spec, comment)

    # Create a dictionary with the selected metadata evaluated.
    metadata_as_dict = {key: getattr(fields, key)() for key in metadata_to_include}

    warn_on_old_pyyaml()
    metadata_as_yaml = (
        "---\n"
        + yaml.dump(data={"conda-lock-metadata": metadata_as_dict}, Dumper=Dumper)
        + "..."
    )

    metadata_as_commented_yaml = "\n".join(
        [f"# {line}" for line in metadata_as_yaml.splitlines()]
    )
    return metadata_as_commented_yaml + "\n"


def _previous_metadata_header(spec: LockSpecification) -> str:
    """We should get rid of this soon, if possible."""
    return "\n".join(
        [
            "# Generated by conda-lock.",
            f"# platform: {spec.platform}",
            f"# input_hash: {spec.input_hash()}\n",
        ]
    )


# PyYAML stuff
# ------------


@lru_cache()  # The following function should run at most once.
def warn_on_old_pyyaml():
    """Versions of PyYAML less than 5.1 sort keys alphabetically."""
    yaml_dumper_params = inspect.signature(yaml.Dumper).parameters
    if "sort_keys" not in yaml_dumper_params:
        print(
            f"WARNING: The currently-installed version of PyYAML (v{yaml.__version__}) "
            "is very old, and the metadata keys will be sorted in alphabetical order "
            "instead of the given order. Please upgrade PyYAML to v5.1 or greater.",
            file=sys.stderr,
        )


def literal_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    """This tells PyYAML to format a given string as a literal block.

    This means that that the '|' delimiter is used, and the text is indented, but
    otherwise unformatted.
    """
    literal_scalar_node = dumper.represent_scalar(STR_TAG, data, style="|")
    return literal_scalar_node


class Dumper(yaml.Dumper):
    """Dumper class for changing PyYAML output defaults."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Prevent alphabetical sorting.
        self.sort_keys = False

        # Don't escape unicode characters.
        self.allow_unicode = True

        # Don't wrap long lines.
        self.width = self.best_width = float("inf")

        # Register all instances of LiteralStr to be formatted as literal blocks.
        self.add_representer(LiteralStr, literal_representer)
