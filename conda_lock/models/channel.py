"""
Conda lock supports two kinds of credentials used for channels:

## Token based

These are used by anaconda.org, Anaconda Enterprise, and Quetz.
To pass one of these channels, specify them in your source with an environment variable.
Make sure this environment variable is not expanded.

Example:
--channel 'http://host.com/t/$MY_REPO_TOKEN/channel'
# TODO: Detect environment variables that match a channel specified incorrectly.

## Simple Auth

For other channels (such as those self-managed), you may be using standard
username/password auth:

Example:
--channel 'http://$USER:$PASSWORD@host.com/channel'

## What gets stored

Since credential parts are both volatile and secret, conda-lock will not store
the raw version of a URL. If it encounters a channel URL that contains credentials,
it will search the available environment variables for a match. When found, that portion
of the URL will be replaced with an environment variable.

Since conda also performs env var substitution, the rendered output can contain env vars
which will be handled correctly by conda/mamba.
"""

import copy
import logging
import os
import re

from posixpath import expandvars
from typing import Any, FrozenSet, List, Optional, Tuple, cast
from urllib.parse import unquote, urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)
token_pattern = re.compile(r"(.*)(/t/\$?\{?[a-zA-Z0-9-_]*\}?)(/.*)")


class CondaUrl(BaseModel):
    raw_url: str
    env_var_url: str
    token: Optional[str] = None
    token_env_var: Optional[str] = None
    user: Optional[str] = None
    user_env_var: Optional[str] = None
    password: Optional[str] = None
    password_env_var: Optional[str] = None


class ZeroValRepr(BaseModel):
    """Helper that hides falsy values from repr."""

    def __repr_args__(self) -> List[Tuple[str, Any]]:
        return [(key, value) for key, value in self.__dict__.items() if value]


class Channel(ZeroValRepr):
    model_config = ConfigDict(frozen=True)
    url: str
    used_env_vars: FrozenSet[str] = Field(default_factory=frozenset)

    @classmethod
    def from_string(cls, value: str) -> "Channel":
        if "://" in value:
            conda_url = _conda_url_from_string(value)
            channel = _channel_from_conda_url(conda_url)
            return channel
        return cls(url=value, used_env_vars=frozenset())

    def env_replaced_url(self) -> str:
        return expandvars(self.url)

    def conda_token_replaced_url(self) -> str:
        """Handle conda's token replacement in the output URL."""
        # TODO: pass in env vars maybe?
        expanded_url = expandvars(self.url)
        if token_pattern.match(expanded_url):
            replaced = token_pattern.sub(r"\1\3", expanded_url, 1)
            p = urlparse(replaced)
            replaced = urlunparse(p._replace(path="/t/<TOKEN>" + p.path))
            return replaced
        return expanded_url


def _detect_used_env_var(
    value: str, preferred_env_var_suffix: List[str]
) -> Optional[str]:
    """Detect if the string exactly matches any current environment variable.

    Preference is given to variables that end in the provided suffixes.
    """
    if value.startswith("$"):
        return value.lstrip("$").strip("{}")

    for suffix in [*preferred_env_var_suffix, ""]:
        candidates = {v: k for k, v in os.environ.items() if k.upper().endswith(suffix)}
        # Try first with a simple match
        if key := candidates.get(value):
            return key
        # Try with unquote
        if key := candidates.get(unquote(value)):
            return key
    return None


def _conda_url_from_string(url: str) -> CondaUrl:
    """Normalize URL by using environment variables."""
    res = urlparse(url)

    def make_netloc(
        username: Optional[str], password: Optional[str], host: str, port: Optional[int]
    ) -> str:
        host_info = f"{host}:{port}" if port else host
        if not username:
            return host_info

        user_info = f"{username}:{password}" if password else username
        return f"{user_info}@{host_info}"

    user_env_var: Optional[str] = None
    password_env_var: Optional[str] = None
    token_env_var: Optional[str] = None

    def get_or_raise(val: Optional[str]) -> str:
        if val is None:
            raise ValueError("Expected to be non-null")
        return val

    res_replaced = copy.copy(res)

    if res.username:
        user_env_var = _detect_used_env_var(res.username, ["USERNAME", "USER"])
        if user_env_var:
            res_replaced = res_replaced._replace(
                netloc=make_netloc(
                    username=f"${{{user_env_var}}}",
                    password=res_replaced.password,
                    host=get_or_raise(res_replaced.hostname),
                    port=res_replaced.port,
                )
            )

    if res.password:
        password_env_var = _detect_used_env_var(
            res.password, ["PASSWORD", "PASS", "TOKEN", "KEY"]
        )
        if password_env_var:
            res_replaced = res_replaced._replace(
                netloc=make_netloc(
                    username=res_replaced.username,
                    password=f"${{{password_env_var}}}",
                    host=get_or_raise(res_replaced.hostname),
                    port=res_replaced.port,
                )
            )

    _token_match = token_pattern.search(res.path)
    token = _token_match.groups()[1][3:] if _token_match else None
    if token:
        token_env_var = _detect_used_env_var(
            token, ["TOKEN", "CRED", "PASSWORD", "PASS", "KEY"]
        )
        if not token_env_var:
            # Maybe we should raise here if we have mismatched env vars
            logger.warning("Token URL detected without env var")
        else:
            new_path = token_pattern.sub(
                rf"\1/t/${{{token_env_var}}}\3", res_replaced.path
            )
            res_replaced = res_replaced._replace(path=new_path)

    return CondaUrl(
        raw_url=url,
        env_var_url=urlunparse(res_replaced),
        user=res.username,
        user_env_var=user_env_var,
        password=res.password,
        password_env_var=password_env_var,
        token=token,
        token_env_var=token_env_var,
    )


def _channel_from_conda_url(conda_url: CondaUrl) -> Channel:
    conda_url = conda_url
    env_vars = {
        conda_url.user_env_var,
        conda_url.token_env_var,
        conda_url.password_env_var,
    }
    env_vars.discard(None)
    return Channel(
        url=conda_url.env_var_url,
        used_env_vars=frozenset(cast(FrozenSet[str], env_vars)),
    )
