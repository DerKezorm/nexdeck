"""Adapter registry: every module in this package that defines ``ADAPTER``."""

from __future__ import annotations

import importlib
import pkgutil

from .base import Adapter

REGISTRY: dict[str, Adapter] = {}


def _load() -> None:
    if REGISTRY:
        return
    package = __name__
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name in ("base", "demo"):
            continue
        module = importlib.import_module(f"{package}.{module_info.name}")
        adapter = getattr(module, "ADAPTER", None)
        if isinstance(adapter, Adapter):
            if adapter.kind in REGISTRY:
                raise RuntimeError(f"Two adapters claim the kind {adapter.kind!r}.")
            REGISTRY[adapter.kind] = adapter


def all_adapters() -> list[Adapter]:
    _load()
    return sorted(REGISTRY.values(), key=lambda a: (a.category, a.label))


def get_adapter(kind: str) -> Adapter:
    _load()
    try:
        return REGISTRY[kind]
    except KeyError as error:
        raise KeyError(f"Unknown adapter kind {kind!r}.") from error


def split_widget_kind(widget_kind: str) -> tuple[Adapter, str]:
    """``"docker.containers"`` -> (docker adapter, ``"containers"``)."""
    adapter_kind, _, kind = widget_kind.partition(".")
    adapter = get_adapter(adapter_kind)
    adapter.widget(kind)
    return adapter, kind
