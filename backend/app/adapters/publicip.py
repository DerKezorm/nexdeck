"""The address this installation has on the internet, and when it changes.

No account and no key: one of two public services is asked what address the
request came from. ipify answers with the address and nothing else, and has
no limit worth mentioning; ipwho.is adds the provider and the place, and is
free for personal use within a monthly allowance.

The address a card saw last is kept per card, in memory. A second card that
asks for IPv6 must not read the first one's IPv4 as a change, and after a
restart the first answer is the new starting point rather than a change.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

IPIFY = {"4": "https://api.ipify.org", "any": "https://api64.ipify.org"}
IPWHOIS = "https://ipwho.is/"

#: How long a card says its address has just changed.
FRESH_SECONDS = 3600


def _address(value: Any) -> str:
    """The answer's address, or an error: whatever else it holds is not shown as an address."""
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        raise AdapterError("The address service answered without an address.", code="bad_answer",
                           hint="Try the other service in the card's settings.") from None


def masked(address: str) -> str:
    """All but the last block hidden: 203.0.113.57 becomes •••.•••.•••.57."""
    if ":" in address:
        return "•••:" + address.rsplit(":", 1)[-1]
    return ".".join(["•••"] * 3 + [address.rsplit(".", 1)[-1]])


class PublicIpAdapter(Adapter):
    kind = "publicip"
    label = "Public IP address"
    category = "network"
    description = "The address your connection has on the internet, and when it changes."
    icon = "lucide:globe"
    beta = False
    needs_integration = False
    keywords = ("WAN", "IP", "DDNS", "external address")
    widgets = (
        WidgetType(
            kind="address",
            label="Public IP address",
            description="The address, and the one before when it changes.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=900,
            options=(
                Field("provider", "Service", type="select", default="ipify",
                      options=(("ipify", "ipify: the address only"), ("ipwhois", "ipwho.is: with provider and place")),
                      help="ipwho.is is free for personal use and limits how often it may be asked each month."),
                Field("family", "Address", type="select", default="4",
                      options=(("4", "IPv4"), ("any", "IPv6 where there is one")), only_when=("provider", "ipify")),
                Field("mask", "Show only the last block", type="bool", default=False,
                      help="For a board that guests see: the rest of the address is dotted out."),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def _ask(self, options: dict[str, Any], ctx: Context) -> tuple[str, list[dict[str, Any]]]:
        """The address and what the service says about it."""
        provider = str(options.get("provider") or "ipify")
        url = IPWHOIS if provider == "ipwhois" else IPIFY.get(str(options.get("family") or "4"), IPIFY["4"])
        # A minute, so that three cards refreshing together ask once.
        response = await ctx.request("GET", url, params=None if provider == "ipwhois" else {"format": "json"}, cache_seconds=60)
        if response.status_code >= 400:
            raise AdapterError(
                f"The address service answered with HTTP {response.status_code}.", code="http_error",
                hint="A longer refresh interval, or the other service in the card's settings, usually helps.",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise AdapterError("The address service answered with something that is not JSON.", code="bad_answer")
        if provider == "ipwhois" and payload.get("success") is False:
            raise AdapterError(f"ipwho.is refused: {payload.get('message') or 'no reason given'}.", code="refused",
                               hint="Its free allowance may be used up; ipify has none.")
        chips: list[dict[str, Any]] = []
        if provider == "ipwhois":
            connection = payload.get("connection") if isinstance(payload.get("connection"), dict) else {}
            operator = connection.get("isp") or connection.get("org")
            place = ", ".join(str(part) for part in (payload.get("city"), payload.get("country")) if part)
            if operator:
                chips.append({"label": "Provider", "value": str(operator)})
            if place:
                chips.append({"label": "Place", "value": place})
        return _address(payload.get("ip")), chips

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        address, chips = await self._ask(options, ctx)
        now = time.time()
        key = f"publicip:{ctx.widget_id}"
        last = ctx.cache.get(key)
        before, changed_at = None, None
        if isinstance(last, dict):
            before, changed_at = last.get("before"), last.get("changed_at")
            if last.get("address") not in (None, address):
                before, changed_at = last["address"], now
        ctx.cache[key] = {"address": address, "before": before, "changed_at": changed_at}
        mask = bool(options.get("mask"))
        shown = masked(address) if mask else address
        if before:
            chips.append({"label": "Before", "value": masked(before) if mask else before})
        fresh = changed_at is not None and now - changed_at < FRESH_SECONDS
        return WidgetData(
            status="warn" if fresh else "ok",
            primary={"label": "Address", "value": shown},
            secondary=chips,
            meta={"status_reason": "The address changed within the last hour." if fresh else ""},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        # From the range set aside for documentation, never anybody's real address.
        address = "203.0.113.57"
        chips = [{"label": "Provider", "value": "Example Telecom"}, {"label": "Place", "value": "Berlin, Germany"}] if options.get("provider") == "ipwhois" else []
        return WidgetData(status="ok", primary={"label": "Address", "value": masked(address) if options.get("mask") else address}, secondary=chips)


ADAPTER = PublicIpAdapter()
