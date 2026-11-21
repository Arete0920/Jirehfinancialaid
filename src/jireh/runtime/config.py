"""Fail-closed, host-neutral configuration for the standalone Jireh runtime.

This module intentionally has no Django dependency so configuration failures
can be verified before application startup and in lightweight contract CI.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from typing import Mapping


_HOST_RE = re.compile(
    r"\A(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z"
)


class RuntimeConfigurationError(ValueError):
    """Refuse to start rather than silently use insecure test defaults."""


@dataclass(frozen=True)
class RuntimeConfig:
    secret_key: str = field(repr=False)
    allowed_hosts: tuple[str, ...]
    db_name: str
    db_user: str
    db_password: str = field(repr=False)
    db_host: str
    db_port: int
    db_sslrootcert: str


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeConfigurationError(f"{name} must be set without outer whitespace")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RuntimeConfigurationError(f"{name} contains control characters")
    return value


def _host(value: str, name: str) -> str:
    lowered = value.lower()
    if not _HOST_RE.fullmatch(lowered):
        raise RuntimeConfigurationError(f"{name} must be a hostname or IPv4 address, without scheme, port or wildcard")
    return lowered


def read_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    """Require an explicitly enabled runtime, a real secret, and PostgreSQL TLS.

    No defaults are supplied for host identity, database credentials, or CA.
    The CA file is checked for presence, but its trust is established by libpq
    only when a database connection uses sslmode=verify-full.
    """
    source = os.environ if env is None else env
    if source.get("JIREH_ENABLE_RUNTIME") != "1":
        raise RuntimeConfigurationError("JIREH_ENABLE_RUNTIME=1 is required")

    secret = _required(source, "JIREH_SECRET_KEY")
    if len(secret) < 50 or secret.startswith("test-only--"):
        raise RuntimeConfigurationError("JIREH_SECRET_KEY must be a non-test secret of at least 50 characters")

    raw_hosts = _required(source, "JIREH_ALLOWED_HOSTS")
    hosts = tuple(_host(part, "JIREH_ALLOWED_HOSTS") for part in raw_hosts.split(","))
    if len(hosts) != len(set(hosts)):
        raise RuntimeConfigurationError("JIREH_ALLOWED_HOSTS must not contain duplicate hosts")

    name = _required(source, "JIREH_DB_NAME")
    user = _required(source, "JIREH_DB_USER")
    password = _required(source, "JIREH_DB_PASSWORD")
    host = _host(_required(source, "JIREH_DB_HOST"), "JIREH_DB_HOST")
    port_str = source.get("JIREH_DB_PORT", "5432")
    if not isinstance(port_str, str) or not port_str.isascii() or not port_str.isdecimal():
        raise RuntimeConfigurationError("JIREH_DB_PORT must be a decimal port")
    port = int(port_str)
    if not 1 <= port <= 65535:
        raise RuntimeConfigurationError("JIREH_DB_PORT must be between 1 and 65535")

    ca = Path(_required(source, "JIREH_DB_SSLROOTCERT"))
    if not ca.is_absolute() or not ca.is_file():
        raise RuntimeConfigurationError("JIREH_DB_SSLROOTCERT must name an existing absolute CA file")

    return RuntimeConfig(
        secret_key=secret,
        allowed_hosts=hosts,
        db_name=name,
        db_user=user,
        db_password=password,
        db_host=host,
        db_port=port,
        db_sslrootcert=str(ca),
    )
