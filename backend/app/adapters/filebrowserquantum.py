"""FileBrowser Quantum: the files of a server in the browser, and what they take.

Measured on 01.10.2026 against gtstef/filebrowser:stable (the 1.5 line) with
one source of three files and a folder, with a right, a wrong and no token.

A token is made in FileBrowser's settings or by a signed-in admin with
``POST /api/auth/token?name=…&days=…&permissions=api``, and sent as
``Authorization: Bearer``. A wrong token answers 401 "invalid token", none at
all 401 "no token present in request".

⚠️ ``/api/settings/sources`` hands out each source of the signed-in user with
``used`` (what the indexed files take), ``total`` (the size of the disk it
lies on) and the counts of files and folders. Until the first scan is done
the numbers are not there yet, and ``status`` says so; the card is amber
then, not wrong.

⚠️ FileBrowser answers every request that carried a good token with a
session cookie, ``filebrowser_quantum_jwt``, and a client that keeps it got
through afterwards with a wrong token: measured, 200. nexdeck's clients keep
no cookies (``outbound_client``), so each request stands on its own token;
a probe with an ordinary client measures nothing about tokens after its
first good one.
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
)


class FileBrowserQuantumAdapter(Adapter):
    kind = "filebrowserquantum"
    label = "FileBrowser Quantum"
    category = "nas"
    description = "What the files of each source take on their disk, how many there are, and the open shares."
    icon = "filebrowser-quantum"
    beta = True
    docs_url = "https://filebrowserquantum.com/en/docs/reference/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://filebrowser:80"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Made in FileBrowser's settings under API tokens, with the permission api."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="storage",
            label="Storage",
            description="Each source with what its files take of the disk, and the files and shares in all.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=300,
            metrics=("used",),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", cache_seconds=30,
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"FileBrowser answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("FileBrowser did not answer with JSON; is this the address of FileBrowser Quantum?", code="bad_answer") from None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        sources = await self._get(config, ctx, "/api/settings/sources")
        return f"FileBrowser answers with {len(sources) if isinstance(sources, dict) else 0} source(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        sources = await self._get(config, ctx, "/api/settings/sources")
        # The shares need the share permission; a token without it still shows the storage.
        try:
            shares = await self._get(config, ctx, "/api/share/list")
        except AdapterError:
            shares = None
        return storage_of(sources if isinstance(sources, dict) else {}, shares if isinstance(shares, list) else None)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        tib = 1024 ** 4
        media = fake.walk("fbq-media", tick, 2.1, 2.3, period=3000)
        return storage_of({
            "media": {"name": "media", "used": int(media * tib), "total": 4 * tib, "numFiles": 18_204, "numDirs": 1_310, "status": "ready"},
            "documents": {"name": "documents", "used": int(0.04 * tib), "total": 1 * tib, "numFiles": 3_877, "numDirs": 402, "status": "ready"},
        }, [{"hash": "a"}, {"hash": "b"}, {"hash": "c"}])


def storage_of(sources: dict[str, Any], shares: list[Any] | None) -> WidgetData:
    """One row per source, its share of the disk as a bar, and what the files are in all."""
    rows: list[dict[str, Any]] = []
    files = 0
    used_all = 0
    scanning = False
    for key, source in sources.items():
        if not isinstance(source, dict):
            continue
        used = int(source.get("used") or 0)
        total = int(source.get("total") or 0)
        files += int(source.get("numFiles") or 0)
        used_all += used
        scanning = scanning or str(source.get("status") or "ready") != "ready"
        rows.append({
            "label": str(source.get("name") or key),
            "value": round(100 * used / total, 1) if total else None,
            "unit": "%",
            "hint": f"{human_bytes(used)} of {human_bytes(total)} · {int(source.get('numFiles') or 0)} files",
        })
    secondary = [*rows, {"label": "Files", "value": files}]
    if shares is not None:
        secondary.append({"label": "Shares", "value": len(shares)})
    return WidgetData(
        status="warn" if scanning else "ok",
        primary={"label": "Used", "value": human_bytes(used_all), "metric": "used"},
        secondary=secondary,
        metrics={"used": float(used_all)},
        meta={"status_reason": "A source is still being indexed." if scanning else ""},
    )


ADAPTER = FileBrowserQuantumAdapter()
