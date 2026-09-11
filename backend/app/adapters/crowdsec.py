"""CrowdSec: which addresses this installation has blocked, and why.

Measured against CrowdSec 1.8.1 on 11.09.2026, with a bouncer key and three
decisions made there by hand: a ban, a captcha on a range, a short ban.

The card talks to the local API the way a bouncer does, with a key from
``cscli bouncers add``. A bouncer may read decisions and nothing else, which
is exactly what a dashboard needs and nothing it should have.

⚠️ No decision at all is answered with the JSON ``null``, not an empty list.

⚠️ A decision's ``duration`` is the time left, as Go writes it: ``29m29s``,
``23h59m55s``.

⚠️ Without a filter the list includes the community blocklist, which on an
enrolled installation is tens of thousands of addresses in one answer. The
cards ask for this installation's own decisions unless told otherwise.
"""

from __future__ import annotations

import re
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
)

#: Decisions this installation made itself: its own scenarios and the command line.
OWN_ORIGINS = "crowdsec,cscli"
GO_DURATION = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")
TYPE_WORD = {"ban": "Ban", "captcha": "Captcha"}


def _seconds(duration: Any) -> float:
    """``23h59m55s`` in seconds; anything unreadable is 0."""
    unit = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(number) * unit[suffix] for number, suffix in GO_DURATION.findall(str(duration or "")))


class CrowdSecAdapter(Adapter):
    kind = "crowdsec"
    label = "CrowdSec"
    category = "network"
    description = "Which addresses this installation has blocked, and why."
    icon = "crowdsec"
    beta = False
    docs_url = "https://docs.crowdsec.net/docs/local_api/intro"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://crowdsec:8080",
              help="The local API, port 8080 by default."),
        Field("api_key", "Bouncer key", type="password", secret=True, required=True,
              help="Made with cscli bouncers add nexdeck. It may only read decisions, which is all the cards need."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="decisions", label="Blocked addresses", description="Addresses and ranges under a ban or a captcha, the newest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("blocked",),
                   options=(Field("limit", "Entries", type="number", default=10),
                            Field("community", "Include the community blocklist", type="bool", default=False,
                                  help="On an enrolled installation that is tens of thousands of addresses."))),
        WidgetType(kind="summary", label="Blocked", description="How many addresses this installation blocks right now.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("blocked",)),
    )

    async def _decisions(self, config: dict[str, Any], ctx: Context, community: bool = False, cache: float = 10) -> list[dict[str, Any]]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/v1/decisions", headers={"X-Api-Key": str(config.get("api_key") or "")},
            params=None if community else {"origins": OWN_ORIGINS},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # Measured: a missing and a wrong key both get 403 "access forbidden".
        if response.status_code in (401, 403):
            raise AuthFailed("CrowdSec rejected the bouncer key.")
        if response.status_code >= 400:
            raise AdapterError(f"CrowdSec answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the local API, usually on port 8080.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("CrowdSec did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than the local API.") from error
        if answer is None:
            return []
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way CrowdSec does.", code="not_crowdsec")
        return [decision for decision in answer if isinstance(decision, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        decisions = await self._decisions(config, ctx, cache=0)
        return f"CrowdSec answers: {len(decisions)} decisions made by this installation are active."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return self._summary(await self._decisions(config, ctx))
        return self._list(await self._decisions(config, ctx, community=bool(options.get("community"))), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(decisions: list[dict[str, Any]]) -> WidgetData:
        captchas = sum(1 for one in decisions if str(one.get("type")).lower() == "captcha")
        ranges = sum(1 for one in decisions if str(one.get("scope")).lower() == "range")
        secondary: list[dict[str, Any]] = [{"label": "Bans", "value": len(decisions) - captchas}]
        secondary += [{"label": label, "value": value} for label, value in (("Captchas", captchas), ("Ranges", ranges)) if value]
        return WidgetData(
            status="ok",
            primary={"label": "Blocked", "value": len(decisions)},
            secondary=secondary,
            metrics={"blocked": float(len(decisions))},
        )

    @staticmethod
    def _list(decisions: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        newest = sorted(decisions, key=lambda one: int(one.get("id") or 0), reverse=True)
        items = []
        for decision in newest[: int(options.get("limit") or 10)]:
            kind = str(decision.get("type") or "").lower()
            scenario = str(decision.get("scenario") or "").removeprefix("crowdsecurity/")
            parts = (TYPE_WORD.get(kind, kind.capitalize()), scenario, "" if decision.get("origin") in ("crowdsec", "cscli") else str(decision.get("origin") or ""))
            left = _seconds(decision.get("duration"))
            items.append({
                "title": str(decision.get("value") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "status": "warn" if kind == "ban" else "unknown",
                "value": duration_short(left) if left else "",
            })
        ranges = sum(1 for one in decisions if str(one.get("scope")).lower() == "range")
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Blocked", "value": len(decisions)}] + ([{"label": "Ranges", "value": ranges}] if ranges else []),
            meta={"empty": "Nothing is blocked right now."},
            metrics={"blocked": float(len(decisions))},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        extra = fake.flicker("cs-new", tick, 0.5)
        decisions = [
            {"id": 41, "type": "ban", "scope": "Ip", "value": "203.0.113.7", "origin": "crowdsec", "scenario": "crowdsecurity/ssh-bf", "duration": f"{3 - tick % 3}h12m"},
            {"id": 38, "type": "ban", "scope": "Ip", "value": "198.51.100.23", "origin": "crowdsec", "scenario": "crowdsecurity/http-probing", "duration": "2h40m"},
            {"id": 35, "type": "captcha", "scope": "Range", "value": "192.0.2.0/24", "origin": "cscli", "scenario": "manual range", "duration": "20h5m"},
        ]
        if extra:
            decisions.insert(0, {"id": 44, "type": "ban", "scope": "Ip", "value": "203.0.113.99", "origin": "crowdsec", "scenario": "crowdsecurity/http-bad-user-agent", "duration": "3h59m"})
        if widget_kind == "summary":
            return self._summary(decisions)
        return self._list(decisions, options)


ADAPTER = CrowdSecAdapter()
