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
    _name_the_connections_a_button_can_act_on()


def _name_the_connections_a_button_can_act_on() -> None:
    """Fill the button card's connection picker with the kinds that declare a
    deed, and only those.

    ⚠️ Here rather than in ``core.py``: the answer is "every adapter that
    declares one", and core cannot ask that at import time without importing
    the whole registry it is part of. Written out by hand it would be a list
    that quietly goes stale the day an adapter declares its first deed, and the
    field's own help text already promises "only connections that offer
    something a button may trigger". A promise a field does not keep is worse
    than no promise: the picker offered all twenty-eight, and picking one of
    the twenty-five that can do nothing led to an empty Action list with no
    word about why.
    """
    from dataclasses import replace

    able = tuple(sorted((kind, one.label) for kind, one in REGISTRY.items() if one.deeds))
    core = REGISTRY.get("core")
    if core is None:
        return
    widgets = []
    for widget in core.widgets:
        if widget.kind != "button":
            widgets.append(widget)
            continue
        options = tuple(
            replace(field, options=able) if field.name == "service" else field
            for field in widget.options
        )
        widgets.append(replace(widget, options=options))
    core.widgets = tuple(widgets)


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
