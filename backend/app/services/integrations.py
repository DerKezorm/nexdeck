"""Integration configuration: secrets in, secrets out.

Secret fields are encrypted before they reach the database and decrypted
only for the adapter. The API never returns a secret; it returns whether one
is set, and an edit that leaves the field empty keeps the stored value.
"""

from __future__ import annotations

from typing import Any

from ..adapters import get_adapter
from ..adapters.base import Field
from ..crypto import decrypt, encrypt, is_encrypted
from ..models import Integration

SECRET_PLACEHOLDER = "********"


def _fields(kind: str) -> tuple[Field, ...]:
    return get_adapter(kind).fields


def store_config(kind: str, incoming: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge an incoming config over the existing one, encrypting secrets."""
    result: dict[str, Any] = dict(existing or {})
    for f in _fields(kind):
        if f.name not in incoming:
            if f.name not in result and f.default is not None:
                result[f.name] = f.default
            continue
        value = incoming[f.name]
        if f.secret:
            if value in (None, "", SECRET_PLACEHOLDER):
                continue
            result[f.name] = encrypt(str(value))
        elif f.type == "bool":
            result[f.name] = bool(value)
        elif f.type == "number":
            try:
                result[f.name] = float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                result[f.name] = None
        else:
            result[f.name] = "" if value is None else str(value).strip()
    return result


def resolve_config(integration: Integration) -> dict[str, Any]:
    """The config as the adapter needs it: secrets decrypted."""
    config = dict(integration.config or {})
    for f in _fields(integration.kind):
        if f.secret and isinstance(config.get(f.name), str):
            config[f.name] = decrypt(config[f.name])
    return config


def public_config(integration: Integration) -> dict[str, Any]:
    """The config as the API shows it: secrets replaced by a marker."""
    config = dict(integration.config or {})
    for f in _fields(integration.kind):
        if f.secret:
            config[f.name] = SECRET_PLACEHOLDER if config.get(f.name) else ""
    return config


def export_config(integration: Integration) -> dict[str, Any]:
    """The config for a board file: secrets become environment references."""
    config = dict(integration.config or {})
    for f in _fields(integration.kind):
        if f.secret and config.get(f.name):
            env_name = f"NEXDECK_{integration.kind}_{integration.id}_{f.name}".upper()
            config[f.name] = "${" + env_name + "}"
    return config


def validate_required(kind: str, config: dict[str, Any]) -> list[str]:
    """Names of required fields that are missing."""
    missing: list[str] = []
    for f in _fields(kind):
        if not f.required:
            continue
        value = config.get(f.name)
        if value in (None, ""):
            missing.append(f.name)
    return missing


def has_plain_secrets(integration: Integration) -> bool:
    return any(
        f.secret and isinstance(integration.config.get(f.name), str)
        and integration.config[f.name] and not is_encrypted(integration.config[f.name])
        for f in _fields(integration.kind)
    )
