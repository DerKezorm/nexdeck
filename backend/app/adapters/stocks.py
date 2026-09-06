"""Share prices: a handful of symbols with what they did today.

Yahoo's chart address answers without a key and gives the last price and the
previous close in one call, which is everything a small card shows. It is not
a documented product, so the card is built to survive a symbol that stops
answering rather than to trust the whole answer.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

API = "https://query1.finance.yahoo.com/v8/finance/chart"
#: Yahoo turns away a request that does not look like a browser.
AGENT = "Mozilla/5.0 (compatible; nexdeck/0.1; +https://github.com/DerKezorm/nexdeck)"

PRESETS = {
    "indices": "^GDAXI\n^GSPC\n^IXIC",
    "tech": "AAPL\nMSFT\nNVDA\nGOOGL",
    "crypto": "BTC-EUR\nETH-EUR",
    "": "",
}
PRESET_OPTIONS = (
    ("indices", "Indices"),
    ("tech", "Technology"),
    ("crypto", "Crypto"),
    ("", "Own list only"),
)


class StocksAdapter(Adapter):
    kind = "stocks"
    label = "Share prices"
    category = "feeds"
    description = "A few symbols with the last price and the day's change."
    icon = "lucide:activity"
    docs_url = "https://finance.yahoo.com/"
    needs_integration = False
    widgets = (
        WidgetType(
            kind="quotes",
            label="Prices",
            description="One line per symbol with its price and how far it moved today.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=900,
            options=(
                Field("preset", "Ready-made set", type="select", default="indices", options=PRESET_OPTIONS),
                Field("symbols", "Own symbols", type="textarea", placeholder="AAPL",
                      help="One per line, as Yahoo writes them: AAPL, ^GDAXI, BTC-EUR, SAP.DE. Replaces the ready-made set."),
            ),
        ),
    )

    @staticmethod
    def _symbols(options: dict[str, Any]) -> list[str]:
        own = [line.strip().upper() for line in str(options.get("symbols") or "").splitlines() if line.strip()]
        if own:
            return own[:10]
        preset = PRESETS.get(str(options.get("preset") or "indices"), "")
        return [line for line in preset.splitlines() if line][:10]

    async def _quote(self, ctx: Context, symbol: str) -> dict[str, Any]:
        payload = await ctx.get_json(
            f"{API}/{symbol}",
            params={"range": "1d", "interval": "1d"},
            headers={"User-Agent": AGENT, "Accept": "application/json"},
            cache_seconds=600,
            timeout=20,
        )
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise AdapterError(str((chart["error"] or {}).get("description") or "unknown symbol"), code="bad_symbol")
        results = chart.get("result") or []
        if not results:
            raise AdapterError("no answer for this symbol", code="bad_symbol")
        return (results[0] or {}).get("meta") or {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        meta = await self._quote(ctx, "AAPL")
        return f"The price service answers; AAPL stands at {meta.get('regularMarketPrice', '?')} {meta.get('currency', '')}.".strip()

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        symbols = self._symbols(options)
        if not symbols:
            raise AdapterError("No symbol is set.", code="missing_symbol")
        items: list[dict[str, Any]] = []
        failures: list[str] = []
        risen = 0
        for symbol in symbols:
            try:
                meta = await self._quote(ctx, symbol)
            except AdapterError as error:
                failures.append(f"{symbol}: {error.message}")
                continue
            price = float(meta.get("regularMarketPrice") or 0)
            before = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
            change = round(100.0 * (price - before) / before, 2) if before else 0.0
            risen += 1 if change > 0 else 0
            items.append({
                "title": str(meta.get("shortName") or symbol),
                "subtitle": symbol,
                "value": f"{price:,.2f} {meta.get('currency', '')}".strip(),
                # Green for up, red for down: the only place where red is not a fault.
                "status": "ok" if change > 0 else ("bad" if change < 0 else "unknown"),
                "change": f"{change:+.2f} %",
            })
        return WidgetData(
            status="ok" if items else ("bad" if failures else "warn"),
            items=items,
            secondary=[{"label": "Risen", "value": f"{risen}/{len(items)}"}] if items else [],
            metrics={"risen": float(risen)},
            meta={"failures": failures},
            error=("; ".join(failures) if failures and not items else None),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        from . import demo as fake

        rows = [("DAX", "^GDAXI", 19840.0, "EUR"), ("S&P 500", "^GSPC", 6210.0, "USD"), ("Nasdaq", "^IXIC", 20180.0, "USD")]
        items = []
        risen = 0
        for name, symbol, base, currency in rows:
            change = round(fake.walk(f"stock-{symbol}", tick, -180, 180, period=700) / 100.0, 2)
            risen += 1 if change > 0 else 0
            items.append({
                "title": name,
                "subtitle": symbol,
                "value": f"{base * (1 + change / 100):,.2f} {currency}",
                "status": "ok" if change > 0 else ("bad" if change < 0 else "unknown"),
                "change": f"{change:+.2f} %",
            })
        return WidgetData(
            items=items,
            secondary=[{"label": "Risen", "value": f"{risen}/{len(items)}"}],
            metrics={"risen": float(risen)},
            meta={"failures": []},
        )


ADAPTER = StocksAdapter()
