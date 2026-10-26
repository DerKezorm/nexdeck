"""Gluetun: is the tunnel up, and which address does the world see.

The card that answers the question every downloader behind a VPN raises: does
the traffic really leave through the tunnel. Gluetun's control server says so
itself; it listens on 8000 and has to be published from the container.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    base_url,
)


class GluetunAdapter(Adapter):
    kind = "gluetun"
    label = "Gluetun"
    category = "network"
    description = "Tunnel state, the public address behind it and the forwarded port."
    icon = "gluetun"
    docs_url = "https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/control-server.md"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://gluetun:8000", help="The control server of the container; it has to be published."),
        Field("api_key", "API key", type="password", secret=True, help="Only if the control server was given roles (Gluetun 3.40 and newer)."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="vpn",
            label="Tunnel",
            description="Whether the tunnel is up, from where the world sees it, and the forwarded port.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("up",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = str(config.get("api_key") or "")
        return {"X-API-Key": key} if key else {}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}{path}",
            headers=self._headers(config),
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def _status(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> str:
        """Gluetun renamed the address in 3.35; the older one still answers.

        A rejected key or a host that is not there must not read as a tunnel
        that is down, so those two go through.
        """
        for path in ("/v1/vpn/status", "/v1/openvpn/status"):
            try:
                payload = await self._get(config, ctx, path, cache=cache)
            except (AuthFailed, Unreachable):
                raise
            except AdapterError:
                continue
            state = str((payload or {}).get("status") or "").lower()
            if state:
                return state
        return "unknown"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        state = await self._status(config, ctx, cache=0)
        address = await self._get(config, ctx, "/v1/publicip/ip", cache=0)
        country = (address or {}).get("country") or "?"
        return f"Gluetun answers; the tunnel is {state} and leaves in {country}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        state = await self._status(config, ctx)
        address = await self._get(config, ctx, "/v1/publicip/ip", cache=60) or {}
        running = state == "running"
        port = None
        try:
            forwarded = await self._get(config, ctx, "/v1/portforwarded", cache=300)
            port = int((forwarded or {}).get("port") or 0) or None
        except (AuthFailed, Unreachable):
            raise
        except AdapterError:
            # Not every provider forwards a port; that is not a fault.
            port = None
        country = address.get("country") or "?"
        city = address.get("city") or ""
        return WidgetData(
            status="ok" if running else "bad",
            primary={"label": "Country", "value": country},
            secondary=[
                {"label": "Public address", "value": address.get("public_ip") or "?"},
                {"label": "Region", "value": f"{city} {address.get('region') or ''}".strip() or "?"},
                {"label": "Forwarded port", "value": port if port else "none"},
            ],
            metrics={"up": 1.0 if running else 0.0},
            meta={"status_reason": "The tunnel is not running." if not running else ""},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        down = fake.flicker("gluetun-down", tick, 0.07)
        return WidgetData(
            status="bad" if down else "ok",
            primary={"label": "Country", "value": "Netherlands" if not down else "?"},
            secondary=[
                {"label": "Public address", "value": "198.51.100.42" if not down else "?"},
                {"label": "Region", "value": "Amsterdam North Holland" if not down else "?"},
                {"label": "Forwarded port", "value": 51820 if not down else "none"},
            ],
            metrics={"up": 0.0 if down else 1.0},
            meta={"status_reason": "The tunnel is not running." if down else ""},
        )


ADAPTER = GluetunAdapter()
