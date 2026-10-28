"""dash. (dashdot): CPU, memory, storage and network of the machine it runs on.

Measured against dashdot 6.3.4 on 27.10.2026, once as a plain container and
once as the documentation runs it for the host's numbers
(``--privileged -v /:/mnt/host:ro``).

⚠️ No sign-in, no key: dashdot has no authentication. The endpoints are
``/info`` (the hardware, once: ``os.dash_version``, ``cpu.cores``,
``ram.size``, ``storage[].size``) and ``/load/cpu``, ``/load/ram``,
``/load/storage``, ``/load/network``, ``/load/gpu`` for what changes.

⚠️ Units, measured: ``/load/cpu`` is a list with one entry per core
(``{"load": percent, "temp": 0, "core": n}``, ``temp`` 0 for a sensor it does
not have); ``/load/ram`` is ``{"load": bytes used}``; ``/load/storage`` is a
list of bytes used, one per storage in ``/info``; ``/load/network`` is
``{"up", "down"}`` in **bytes per second**.

⚠️ Without the privileged mount of the host, ``/load/storage`` answers ``[-1]``
(measured): the container cannot see the host's disks. -1 is "unknown", not a
disk that is empty, and the storage card says so.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    measured,
    percent,
    percent_primary,
    status_from_percent,
)


def _mbit(bytes_per_second: Any) -> float | None:
    try:
        return round(float(bytes_per_second) * 8 / 1_000_000, 1)
    except (TypeError, ValueError):
        return None


class DashdotAdapter(Adapter):
    kind = "dashdot"
    label = "dashdot"
    category = "monitoring"
    description = "CPU load, memory, storage and network traffic of the machine dashdot runs on."
    icon = "dashdot"
    #: Measured on 2026-10-27 against dashdot 6.3.4, not yet an instance in use.
    beta = True
    docs_url = "https://getdashdot.com/docs/"
    keywords = ("dash.", "dash dot", "mauricenino")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://dashdot:3001"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="cpu", label="CPU", description="The load of the processor, with the busiest core.",
                   renderer="gauge", default_size=(2, 2), refresh_seconds=15, metrics=("load",)),
        WidgetType(kind="memory", label="Memory", description="How much of the memory is in use.",
                   renderer="gauge", default_size=(2, 2), refresh_seconds=30, metrics=("used",)),
        WidgetType(kind="storage", label="Storage", description="How much of the disks is in use. Needs dashdot's privileged mount of the host.",
                   renderer="gauge", default_size=(2, 2), refresh_seconds=300, metrics=("used",)),
        WidgetType(kind="network", label="Network", description="What the machine receives and sends, in megabits per second.",
                   renderer="value", default_size=(2, 2), refresh_seconds=15, metrics=("down", "up")),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 5) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(f"dashdot answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of dashdot's web page, port 3001 by default.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("dashdot did not answer with JSON.", code="not_json", hint="The URL probably points at a login page or a proxy.") from error

    async def _info(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        info = await self._get(config, ctx, "/info", cache=3600)
        if not isinstance(info, dict) or "cpu" not in info or "ram" not in info:
            raise AdapterError("This address answers, but not the way dashdot does.", code="not_dashdot")
        return info

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._info(config, ctx)
        version = (info.get("os") or {}).get("dash_version")
        return f"dashdot {version} answers, {(info.get('cpu') or {}).get('cores', '?')} cores." if version else "dashdot answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "cpu":
            return self._cpu(await self._get(config, ctx, "/load/cpu"))
        if widget_kind == "network":
            return self._network(await self._get(config, ctx, "/load/network"))
        info = await self._info(config, ctx)
        if widget_kind == "memory":
            return self._memory(await self._get(config, ctx, "/load/ram"), (info.get("ram") or {}).get("size"))
        return self._storage(await self._get(config, ctx, "/load/storage", cache=60), [one.get("size") for one in info.get("storage") or [] if isinstance(one, dict)])

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _cpu(cores: Any) -> WidgetData:
        loads = [float(one["load"]) for one in cores if isinstance(one, dict) and one.get("load") is not None] if isinstance(cores, list) else []
        if not loads:
            raise AdapterError("dashdot reports no processor load.", code="no_data")
        average = round(sum(loads) / len(loads), 1)
        return WidgetData(status=status_from_percent(average), primary=percent_primary("CPU", round(average)),
                          secondary=[{"label": "Busiest core", "value": f"{max(loads):.0f}%"}, {"label": "Cores", "value": len(loads)}],
                          metrics={"load": average})

    @staticmethod
    def _memory(ram: Any, size: Any) -> WidgetData:
        used = ram.get("load") if isinstance(ram, dict) else None
        share = percent(used, size)
        return WidgetData(status=status_from_percent(share), primary=percent_primary("Memory", None if share is None else round(share)),
                          secondary=[{"label": "Used", "value": human_bytes(used)}, {"label": "Total", "value": human_bytes(size)}],
                          metrics=measured({"used": share}))

    @staticmethod
    def _storage(used: Any, sizes: list[Any]) -> WidgetData:
        loads = [float(one) for one in used if isinstance(one, int | float)] if isinstance(used, list) else []
        # ⚠️ Measured: [-1] without the privileged mount of the host. That is "cannot see", not "empty".
        if not loads or any(one < 0 for one in loads):
            return WidgetData(status="unknown", primary=percent_primary("Storage", None),
                              secondary=[{"label": "State", "value": "Needs the host mounted"}],
                              meta={"status_reason": "dashdot cannot see the host's disks; run it privileged with -v /:/mnt/host:ro."})
        total = sum(float(one) for one in sizes if isinstance(one, int | float))
        share = percent(sum(loads), total)
        return WidgetData(status=status_from_percent(share), primary=percent_primary("Storage", None if share is None else round(share)),
                          secondary=[{"label": "Used", "value": human_bytes(sum(loads))}, {"label": "Total", "value": human_bytes(total or None)}],
                          metrics=measured({"used": share}))

    @staticmethod
    def _network(load: Any) -> WidgetData:
        down, up = (_mbit(load.get("down")), _mbit(load.get("up"))) if isinstance(load, dict) else (None, None)
        return WidgetData(primary={"label": "Down", "metric": "down", "value": down, "unit": "Mbit/s" if down is not None else ""},
                          secondary=[{"label": "Up", "metric": "up", "value": up, "unit": "Mbit/s" if up is not None else ""}],
                          metrics=measured({"down": down, "up": up}))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        gib = 1024**3
        if widget_kind == "cpu":
            return self._cpu([{"load": fake.walk(f"dd-core{core}", tick, 2, 70), "temp": 0, "core": core} for core in range(4)])
        if widget_kind == "memory":
            return self._memory({"load": fake.walk("dd-ram", tick, 3, 7) * gib}, 8 * gib)
        if widget_kind == "storage":
            return self._storage([fake.walk("dd-disk", tick, 300, 320) * gib], [500 * gib])
        return self._network({"down": fake.walk("dd-down", tick, 0.1, 40) * 125_000, "up": fake.walk("dd-up", tick, 0.05, 6) * 125_000})


ADAPTER = DashdotAdapter()
