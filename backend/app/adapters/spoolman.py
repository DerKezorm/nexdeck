"""Spoolman: how much filament is left, and which spools are running low.

Measured on 27.10.2026 against Spoolman 0.27.0 (``ghcr.io/donkie/spoolman``)
with a vendor, three filaments and five spools: one fresh, one nearly empty,
one half used, one archived, and one for which nobody knows any weight.

⚠️ Spoolman has no sign-in of its own, so there is no key to check and no 401
to read; the connection test is the only thing that can say the address is
not Spoolman.

⚠️ ``GET /api/v1/spool`` leaves archived spools out unless asked, and that is
what the cards want: an empty spool put on the shelf is not a spool to buy.
The ones that are not archived but empty stay, and show as empty.

⚠️ ``remaining_weight`` is missing, not zero, on a spool whose weight nobody
entered and whose filament has none either. The card says "?" for it and
leaves it out of every sum instead of counting it as an empty spool.

⚠️ ``remaining_weight`` is the filament alone, in grams. ``remaining_length``
is in millimetres, which the cards do not use.
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
    measured,
)

#: A spool is low below this share of what it started with, unless the card says otherwise.
LOW_PERCENT = 15


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _filament(spool: dict[str, Any]) -> dict[str, Any]:
    one = spool.get("filament")
    return one if isinstance(one, dict) else {}


def _name(spool: dict[str, Any]) -> str:
    filament = _filament(spool)
    vendor = filament.get("vendor") if isinstance(filament.get("vendor"), dict) else {}
    parts = [str(vendor.get("name") or "").strip(), str(filament.get("name") or "").strip()]
    return " ".join(part for part in parts if part) or f"Spool {spool.get('id', '?')}"


def _left(spool: dict[str, Any]) -> float | None:
    """Grams of filament left, or None when nobody knows."""
    return _number(spool.get("remaining_weight"))


def _share(spool: dict[str, Any]) -> float | None:
    """How much of the spool is left, in per cent, or None when its size is unknown."""
    left = _left(spool)
    total = _number(spool.get("initial_weight")) or _number(_filament(spool).get("weight"))
    if left is None or not total or total <= 0:
        return None
    return max(0.0, min(100.0, round(left / total * 100, 1)))


def _grams(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value / 1000:.2f} kg" if value >= 1000 else f"{value:.0f} g"


def _low_line(options: dict[str, Any]) -> float:
    try:
        line = float(options.get("low_percent"))
    except (TypeError, ValueError):
        return float(LOW_PERCENT)
    return min(100.0, max(1.0, line))


def _is_low(spool: dict[str, Any], line: float) -> bool:
    share = _share(spool)
    return share is not None and share < line


class SpoolmanAdapter(Adapter):
    kind = "spoolman"
    label = "Spoolman"
    category = "other"
    description = "How much filament is left in total, and which spools are running low."
    icon = "spoolman"
    beta = True
    docs_url = "https://donkie.github.io/Spoolman/"
    keywords = ("3D printer", "filament")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://spoolman:7912"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="stock", label="Filament stock",
            description="The filament left on all spools together, how many spools there are and how many are running low.",
            renderer="value", default_size=(3, 2), refresh_seconds=120,
            metrics=("remaining_kg", "low_spools"),
            parts=(("spools", "Spools"), ("low", "Running low")),
            options=(Field("low_percent", "Running low below (%)", type="number", default=LOW_PERCENT),),
        ),
        WidgetType(
            kind="spools", label="Spools",
            description="Each spool with what is left of it, the emptiest first.",
            renderer="list", default_size=(3, 3), refresh_seconds=120,
            options=(
                Field("low_percent", "Running low below (%)", type="number", default=LOW_PERCENT),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
    )

    # -- talking to Spoolman -------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Accept": "application/json"}, params=params,
            verify=not config.get("insecure"), timeout=10.0, cache_seconds=10)
        if response.status_code >= 400:
            raise AdapterError(f"Spoolman answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address Spoolman's web interface opens at.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than Spoolman.", code="not_spoolman",
                               hint="Check the URL; it is the address Spoolman's web interface opens at.") from error

    async def _spools(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        spools = await self._get(config, ctx, "/spool")
        if not isinstance(spools, list):
            raise AdapterError("This address answers, but not the way Spoolman does.", code="not_spoolman")
        return [spool for spool in spools if isinstance(spool, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/info")
        if not isinstance(info, dict) or "version" not in info:
            raise AdapterError("This address answers, but not the way Spoolman does.", code="not_spoolman",
                               hint="Check the URL; it is the address Spoolman's web interface opens at.")
        count = len(await self._spools(config, ctx))
        return f"Spoolman {info['version']} answers with {count} spools."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        return self._card(widget_kind, await self._spools(config, ctx), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _card(widget_kind: str, spools: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        line = _low_line(options)
        if widget_kind == "spools":
            try:
                limit = max(1, min(50, int(options.get("limit") or 8)))
            except (TypeError, ValueError):
                limit = 8
            # ⚠️ The emptiest first; the ones nobody weighed last, because they cannot be called low.
            ordered = sorted(spools, key=lambda spool: (_share(spool) is None, _share(spool) or 0.0, _name(spool)))
            items = []
            for spool in ordered[:limit]:
                share = _share(spool)
                filament = _filament(spool)
                where = str(spool.get("location") or "").strip()
                material = str(filament.get("material") or "").strip()
                left = _left(spool)
                status = "unknown" if share is None else "bad" if (left or 0) <= 0 else "warn" if share < line else "ok"
                items.append({
                    "id": spool.get("id"),
                    "title": _name(spool),
                    "subtitle": " · ".join(part for part in (material, where) if part),
                    "value": _grams(left),
                    "progress": share,
                    "status": status,
                })
            return WidgetData(
                items=items,
                secondary=[{"label": "Spools", "value": len(spools)}],
                meta={"empty": "No spool in Spoolman."},
            )

        known = [left for left in (_left(spool) for spool in spools) if left is not None]
        total = sum(known)
        low = sum(1 for spool in spools if _is_low(spool, line))
        secondary: list[dict[str, Any]] = [{"label": "Spools", "value": len(spools), "part": "spools"}]
        if low:
            secondary.append({"label": "Running low", "value": low, "part": "low"})
        return WidgetData(
            status="warn" if low else "ok",
            primary={"label": "Filament left", "value": round(total / 1000, 2), "unit": "kg"},
            secondary=secondary,
            metrics=measured({"remaining_kg": round(total / 1000, 3) if known else None, "low_spools": float(low)}),
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        used = fake.walk("spoolman-used", tick, 0, 90, period=900)
        spools = [
            {"id": 1, "filament": {"name": "PLA Signal Red", "material": "PLA", "weight": 1000, "vendor": {"name": "Example Filaments"}},
             "initial_weight": 1000, "remaining_weight": round(820 - used, 1), "location": "Shelf A"},
            {"id": 2, "filament": {"name": "PLA Signal Red", "material": "PLA", "weight": 1000, "vendor": {"name": "Example Filaments"}},
             "initial_weight": 1000, "remaining_weight": 60.0, "location": "Shelf A"},
            {"id": 3, "filament": {"name": "PETG Black", "material": "PETG", "weight": 1000, "vendor": {"name": "Example Filaments"}},
             "initial_weight": 1000, "remaining_weight": round(500 - used / 2, 1), "location": "Printer"},
            {"id": 4, "filament": {"name": "ABS Grey", "material": "ABS", "weight": 750}, "remaining_weight": 705.0},
        ]
        return self._card(widget_kind, spools, options)


ADAPTER = SpoolmanAdapter()
