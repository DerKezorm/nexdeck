"""One container, one guest: the card that shows everything about a single one.

⚠️ One shape for every service, not one card per adapter. What each service
hands out differs a lot (Docker gives network and block IO, Synology gives
neither), and a card that draws the union of all of them would have to invent
the gaps. It does not: a row nobody measured says so, which is what
``percent`` and ``measured`` were built for.

The rows are ordered the same everywhere, so the same card on two services
reads the same way, and a service that cannot answer one of them simply has
one row fewer.
"""

from __future__ import annotations

from typing import Any

from .base import Field, WidgetData, WidgetType, human_bytes, percent, status_from_percent


#: The field that picks which one. Its answers come from the service.
def which_field(label: str, help_text: str, name: str = "which") -> Field:
    return Field(name, label, type="choices", required=True, help=help_text)


def size_field() -> Field:
    return Field("history", "Keep a history", type="bool", default=True,
                 help="Draws the last day under CPU and memory. Off saves a little room in the database.")


def one_of(kind: str, label: str, description: str, refresh: int = 20, *, field: str = "which") -> WidgetType:
    """The widget declaration, identical for every service that offers it.

    ⚠️ ``field`` exists because one service offers this card twice. Synology
    has containers and virtual machines, both cards asked a field called
    ``which``, and the list behind that name held both: the machine card
    offered every container, and picking one answered "there is no machine
    called immich_postgres". A list is answered by field name, so two lists
    need two names.
    """
    return WidgetType(
        kind=kind,
        label=label,
        description=description,
        renderer="stats",
        default_size=(3, 3),
        min_size=(2, 2),
        refresh_seconds=refresh,
        metrics=("cpu", "memory"),
        options=(which_field("Which one", "The list comes from the service.", field), size_field()),
    )


def card(
    *,
    title: str,
    state: str,
    ok_states: tuple[str, ...],
    cpu: float | None,
    memory_used: float | None,
    memory_limit: float | None,
    extra: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    history: bool = True,
) -> WidgetData:
    """The rows, in the order every one of these cards uses them.

    ⚠️ A row whose number nobody measured is left out rather than drawn as
    zero. Zero reads as "measured, and fine", and on a card whose whole job is
    to say how one container is doing that is the worst thing it could say.
    """
    share = percent(memory_used, memory_limit)
    rows: list[dict[str, Any]] = []
    if memory_used is not None:
        rows.append({"label": "Memory", "value": human_bytes(memory_used), "metric": "memory" if history else ""})
    if share is not None:
        rows.append({"label": "Memory used", "value": share, "unit": "%"})
    rows.extend(extra or [])
    rows.append({"label": "State", "value": state or "unknown"})

    measured_now: dict[str, float] = {}
    if history:
        if cpu is not None:
            measured_now["cpu"] = cpu
        if memory_used is not None:
            measured_now["memory"] = memory_used / (1024 * 1024)

    return WidgetData(
        status="ok" if state in ok_states else ("unknown" if not state else "bad"),
        primary={"label": "CPU", "value": cpu, "unit": "%" if cpu is not None else "",
                 "metric": "cpu" if history else ""},
        secondary=rows,
        metrics=measured_now,
        meta={"title": title, "cpu_unit": "%", "memory_unit": "MB",
              "status_reason": "" if state in ok_states else state},
        actions=actions or [],
    )


def worst_of(cpu: float | None, memory_share: float | None) -> str:
    """Green, yellow or red from the two numbers every service does give."""
    return status_from_percent(max([v for v in (cpu, memory_share) if v is not None], default=None))


def demo_card(name: str, tick: int, *, network: bool = True, disk: bool = True, cpu: bool = True) -> WidgetData:
    """Invented numbers for the same card, so a demo board shows one too.

    Which rows appear follows the service: a demo that showed Synology with
    network counters would promise something the real card cannot keep.
    """
    load = 4.0 + (tick % 7) * 1.5
    used = 380 * 1024 * 1024 + (tick % 5) * 12 * 1024 * 1024
    extra: list[dict[str, Any]] = []
    if network:
        extra.append({"label": "Network in", "value": human_bytes(2.1e9 + tick * 1e6)})
        extra.append({"label": "Network out", "value": human_bytes(0.4e9 + tick * 2e5)})
    if disk:
        extra.append({"label": "Disk read", "value": human_bytes(3.2e8)})
        extra.append({"label": "Disk written", "value": human_bytes(1.8e9)})
        extra.append({"label": "Processes", "value": 31})
    extra.append({"label": "Running since", "value": "Up 3 days"})
    extra.append({"label": "Image", "value": "ghcr.io/derkezorm/nexview:latest"})
    return card(
        title=name, state="running", ok_states=("running",),
        cpu=round(load, 1) if cpu else None,
        memory_used=float(used), memory_limit=2.0 * 1024 * 1024 * 1024,
        extra=extra,
    )
