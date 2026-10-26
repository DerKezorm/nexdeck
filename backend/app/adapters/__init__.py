"""Adapter registry: every module in this package that defines ``ADAPTER``."""

from __future__ import annotations

import importlib
import pkgutil

from .base import Adapter

REGISTRY: dict[str, Adapter] = {}
#: The kinds that ship with nexdeck, found when the registry is loaded. Own kinds (``custom:<short>``) come and go.
_BUILTIN: set[str] = set()
CUSTOM_PREFIX = "custom:"
#: The names of the address parameters that the sign-in of the own kinds uses, lower case. Read by the log filter (KARTEN-3 AC-5).
_CUSTOM_PARAMS: frozenset[str] = frozenset()


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
    _BUILTIN.update(REGISTRY)
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


def builtin_kinds() -> frozenset[str]:
    """The kinds that ship with nexdeck: an own connection may not take one of these names (KARTEN-3 EC-1)."""
    _load()
    return frozenset(_BUILTIN)


def builtin_categories() -> frozenset[str]:
    _load()
    return frozenset(REGISTRY[kind].category for kind in _BUILTIN)


def register_custom(adapter: Adapter) -> None:
    """Put an own kind where the built-in ones are, replacing the one of the same name (KARTEN-3 AC-11)."""
    _load()
    if not adapter.kind.startswith(CUSTOM_PREFIX):
        raise ValueError("An own kind is called custom:<short>.")
    REGISTRY[adapter.kind] = adapter
    _note_custom_params()


def unregister_custom(kind: str) -> None:
    REGISTRY.pop(kind, None)
    _note_custom_params()


def forget_all_custom() -> None:
    """Every own kind out of the registry (a new database is read, or a test starts)."""
    for kind in [one for one in REGISTRY if one.startswith(CUSTOM_PREFIX)]:
        del REGISTRY[kind]
    _note_custom_params()


def _note_custom_params() -> None:
    global _CUSTOM_PARAMS
    names: set[str] = set()
    for kind, one in REGISTRY.items():
        auth = getattr(getattr(one, "definition", None), "auth", None) if kind.startswith(CUSTOM_PREFIX) else None
        if auth is None:
            continue
        names.add((auth.param or "").lower())
        if auth.pass_ is not None:
            names.add((auth.pass_.param or "").lower())
    _CUSTOM_PARAMS = frozenset(names - {""})


def custom_credential_params() -> frozenset[str]:
    """The parameters of an address in which an own kind sends its key or its ticket, whatever they are called (KARTEN-3 AC-5).

    ⚠️ ``openapi`` or ``t`` look harmless to the list of credential names (:mod:`..credential_names`), but the definition says
    they carry the key, so the log leaves their value out as long as the kind is in the registry.
    """
    return _CUSTOM_PARAMS


def all_adapters() -> list[Adapter]:
    _load()
    return sorted(REGISTRY.values(), key=lambda a: (a.category, a.label))


def get_adapter(kind: str) -> Adapter:
    _load()
    try:
        return REGISTRY[kind]
    except KeyError as error:
        raise KeyError(f"Unknown adapter kind {kind!r}.") from error


def adapter_or_missing(kind: str) -> Adapter:
    """The adapter of a kind a stored connection has, or a stand-in that says the kind is gone (KARTEN-3 EC-6).

    ⚠️ For everything that walks over stored connections or widgets. Deleting an own kind leaves its connections in the
    database, and a list, a collector or a search that raised ``KeyError`` for one of them would stop for all.
    """
    _load()
    found = REGISTRY.get(kind)
    if found is not None:
        return found
    from .defined import MissingAdapter

    return MissingAdapter(kind)


def split_widget_kind(widget_kind: str) -> tuple[Adapter, str]:
    """``"docker.containers"`` -> (docker adapter, ``"containers"``)."""
    adapter_kind, _, kind = widget_kind.partition(".")
    adapter = get_adapter(adapter_kind)
    adapter.widget(kind)
    return adapter, kind
