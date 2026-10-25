"""Which provider the assistant uses, set once for the installation by an administrator.

Three providers: ``off`` (the default), ``anthropic`` (Claude, through the
official SDK) and ``openai`` (anything that speaks ``/v1/chat/completions``:
OpenAI, Ollama, LM Studio, vLLM, OpenRouter). The key is encrypted under its
own context and never comes back out of the API; the browser only learns
whether one is set.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ... import crypto
from ...models import Setting

SETTING = "assistant"
CONTEXT = "assistant:key"
PROVIDERS = ("off", "anthropic", "openai")
#: The model a new Claude setting starts with; the administrator picks another from the list.
#: Sonnet: looking up cards and the chronicle needs no more, and costs a fraction of Opus.
DEFAULT_MODEL = {"anthropic": "claude-sonnet-5-5", "openai": ""}


class Refused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _value(db: Session) -> dict[str, Any]:
    setting = db.get(Setting, SETTING)
    return dict(setting.value or {}) if setting is not None else {}


def stored(db: Session) -> dict[str, Any]:
    value = _value(db)
    provider = value.get("provider") if value.get("provider") in PROVIDERS else "off"
    return {"provider": provider, "base_url": str(value.get("base_url") or ""), "model": str(value.get("model") or ""),
            "key": str(value.get("key") or "")}


def key_of(db: Session) -> str:
    return crypto.decrypt_for(stored(db)["key"], CONTEXT)


def key_for(db: Session, provider: str, base_url: str, typed: str | None) -> str:
    """The key to ask a service with: the one typed, else the stored one, but only for the stored service.

    ⚠️ A stored key never goes to an address typed elsewhere: whoever could type
    one would otherwise have the key sent to a server of theirs.
    """
    if typed and typed.strip():
        return typed.strip()
    value = stored(db)
    same = provider == value["provider"] and (provider == "anthropic" or base_url.strip().rstrip("/") == value["base_url"])
    return key_of(db) if same and value["key"] else ""


def leaves_the_house(provider: str, base_url: str) -> bool:
    """Whether questions go to a service outside the home network.

    Claude always does. An OpenAI-shaped service does unless its address is
    a private one, a ``.local``/``.lan``/``.home.arpa`` name or a single word.
    """
    if provider == "anthropic":
        return True
    if provider != "openai":
        return False
    host = (urlsplit(base_url).hostname or "").lower()
    if not host:
        return True
    try:
        address = ipaddress.ip_address(host)
        return not (address.is_private or address.is_loopback or address.is_link_local)
    except ValueError:
        return not ("." not in host or host.endswith((".local", ".lan", ".home.arpa", ".internal")))


def public(db: Session) -> dict[str, Any]:
    value = stored(db)
    return {
        "provider": value["provider"], "base_url": value["base_url"], "model": value["model"],
        "has_key": bool(value["key"]), "ready": ready(db),
        "leaves_the_house": leaves_the_house(value["provider"], value["base_url"]),
    }


def ready(db: Session) -> bool:
    value = stored(db)
    if value["provider"] == "anthropic":
        return bool(value["key"] and value["model"])
    if value["provider"] == "openai":
        # Ollama and LM Studio need no key; the address and the model they do.
        return bool(value["base_url"] and value["model"])
    return False


def store(db: Session, *, provider: str, base_url: str, model: str, key: str | None) -> dict[str, Any]:
    """``key=None`` keeps the stored one, ``""`` removes it."""
    if provider not in PROVIDERS:
        raise Refused("bad_provider", "No such provider.")
    base_url = base_url.strip().rstrip("/")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise Refused("bad_address", "The address starts with http:// or https://.")
    if provider == "openai" and not base_url:
        raise Refused("missing_address", "An OpenAI-shaped service needs its address, such as http://ollama:11434/v1.")
    model = model.strip() or DEFAULT_MODEL.get(provider, "")
    if provider != "off" and not model:
        raise Refused("missing_model", "Name the model to use.")
    value = stored(db)
    secret = value["key"] if key is None else crypto.encrypt_for(key.strip(), CONTEXT) if key.strip() else ""
    new = {"provider": provider, "base_url": base_url if provider == "openai" else "", "model": model if provider != "off" else "", "key": secret}
    setting = db.get(Setting, SETTING)
    if setting is None:
        db.add(Setting(key=SETTING, value=new))
    else:
        setting.value = new
    return new
