"""Papra: how much is filed in an organization, and what came in last (issue #42).

The API key is made in Papra under API keys in the user menu and rides as
a bearer token. It needs ``organizations:read`` and ``documents:read``; the
card writes nothing. Everything Papra keeps belongs to an organization, so
every question goes through one: the one named in the connection, or the
first the key can see.

⚠️ Written against Papra's own sources (``apps/papra-server``, October 2026)
and its API page, not yet against a running instance. Hence beta.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
)

#: What the card reads, and what Papra names it on the key.
NEEDED = ("organizations:read", "documents:read")


class PapraAdapter(Adapter):
    kind = "papra"
    label = "Papra"
    category = "other"
    description = "Documents of an organization, their size, and what came in last."
    icon = "papra"
    beta = True
    docs_url = "https://docs.papra.app/resources/api-endpoints/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://papra:1221"),
        Field("token", "API key", type="password", secret=True, required=True,
              help="In Papra under API keys in the user menu, with Read organizations and Read documents."),
        Field("organization", "Organization", placeholder="Household",
              help="Name or ID. Empty means the first organization the key can see."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In Papra, open API keys in the user menu and choose Create API key.",
        "Tick Read organizations and Read documents. The card writes nothing.",
        "Copy the key right away: Papra shows it only once.",
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Documents",
            description="How many documents the organization keeps, their size and the trash.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("documents",),
        ),
        WidgetType(
            kind="recent",
            label="Latest documents",
            description="What came in last, newest first, with its tags.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
        WidgetType(
            kind="organizations",
            label="Organizations",
            description="Every organization the key can see, with its documents and their size.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=900,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 120) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def _organizations(self, config: dict[str, Any], ctx: Context, cache: float = 600) -> list[dict[str, Any]]:
        payload = await self._get(config, ctx, "/organizations", cache=cache)
        rows = (payload or {}).get("organizations") if isinstance(payload, dict) else None
        return [row for row in rows or [] if isinstance(row, dict) and row.get("id")]

    async def _organization(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """The organization the connection names, by ID or by name, or the first one."""
        found = await self._organizations(config, ctx)
        if not found:
            raise AdapterError("The key sees no organization.", code="no_organization",
                               hint="Create one in Papra, or use a key of an account that belongs to one.")
        wanted = str(config.get("organization") or "").strip()
        if not wanted:
            return found[0]
        for row in found:
            if str(row.get("id")) == wanted:
                return row
        for row in found:
            if str(row.get("name") or "").strip().casefold() == wanted.casefold():
                return row
        raise AdapterError(
            f"No organization called {wanted!r}.", code="unknown_organization",
            hint="Known to this key: " + ", ".join(str(row.get("name") or row.get("id")) for row in found[:6]) + ".",
        )

    async def _statistics(self, config: dict[str, Any], ctx: Context, organization_id: str) -> dict[str, Any]:
        payload = await self._get(config, ctx, f"/organizations/{quote(organization_id, safe='')}/documents/statistics", cache=300)
        stats = (payload or {}).get("organizationStats") if isinstance(payload, dict) else None
        return stats if isinstance(stats, dict) else {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        current = await self._get(config, ctx, "/api-keys/current", cache=0)
        key = (current or {}).get("apiKey") if isinstance(current, dict) else None
        allowed = set((key or {}).get("permissions") or [])
        missing = [name for name in NEEDED if name not in allowed]
        if key is not None and missing:
            raise AdapterError(
                "The key lacks " + " and ".join(missing) + ".", code="missing_permission",
                hint="Make a new key in Papra with organizations:read and documents:read.",
            )
        organization = await self._organization(config, ctx)
        return f"Papra answers, organization {organization.get('name') or organization.get('id')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "organizations":
            return await self._every_organization(config, ctx)
        organization = await self._organization(config, ctx)
        organization_id = str(organization["id"])
        if widget_kind == "recent":
            return await self._recent(config, ctx, organization_id, options)
        stats = await self._statistics(config, ctx, organization_id)
        count = _count(stats.get("documentsCount"))
        trash = _count(stats.get("deletedDocumentsCount"))
        secondary: list[dict[str, Any]] = [{"label": "Size", "value": human_bytes(_count(stats.get("documentsSize")))}]
        if trash:
            secondary.append({"label": "In the trash", "value": trash})
        return WidgetData(
            primary={"label": "Documents", "value": count},
            secondary=secondary,
            metrics={"documents": float(count)},
        )

    async def _recent(self, config: dict[str, Any], ctx: Context, organization_id: str, options: dict[str, Any]) -> WidgetData:
        limit = max(1, min(50, int(options.get("limit") or 6)))
        payload = await self._get(
            config, ctx, f"/organizations/{quote(organization_id, safe='')}/documents",
            {"pageIndex": 0, "pageSize": limit, "sortField": "createdAt", "sortOrder": "desc"}, cache=300,
        )
        documents = (payload or {}).get("documents") if isinstance(payload, dict) else None
        base = base_url(config)
        items = []
        for document in documents or []:
            if not isinstance(document, dict):
                continue
            tags = [str(tag.get("name")) for tag in document.get("tags") or [] if isinstance(tag, dict) and tag.get("name")]
            items.append({
                "title": str(document.get("name") or document.get("originalName") or "?"),
                "subtitle": ", ".join(tags[:3]),
                "value": ago(document.get("createdAt")),
                "url": f"{base}/organizations/{quote(organization_id, safe='')}/documents/{quote(str(document.get('id') or ''), safe='')}",
            })
        total = _count((payload or {}).get("documentsCount")) if isinstance(payload, dict) else 0
        return WidgetData(items=items, secondary=[{"label": "Documents", "value": total}], meta={"empty": "No documents yet."})

    async def _every_organization(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        items = []
        for organization in (await self._organizations(config, ctx))[:20]:
            organization_id = str(organization["id"])
            stats = await self._statistics(config, ctx, organization_id)
            items.append({
                "title": str(organization.get("name") or organization_id),
                "subtitle": human_bytes(_count(stats.get("documentsSize"))),
                "value": _count(stats.get("documentsCount")),
                "url": f"{base}/organizations/{quote(organization_id, safe='')}",
            })
        return WidgetData(items=items, meta={"empty": "The key sees no organization."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        total = fake.counter("papra-total", tick, 1240, 0.04)
        if widget_kind == "recent":
            rows = [
                ("Electricity bill", "bills, energy", "2 h"),
                ("Car insurance renewal", "insurance", "1 d"),
                ("Payslip September", "work", "3 d"),
                ("Warranty washing machine", "warranty, home", "6 d"),
                ("Tax assessment", "tax", "12 d"),
            ]
            return WidgetData(
                items=[{"title": title, "subtitle": tags, "value": when} for title, tags, when in rows[: int(options.get("limit") or 6)]],
                secondary=[{"label": "Documents", "value": total}],
            )
        if widget_kind == "organizations":
            return WidgetData(items=[
                {"title": "Household", "subtitle": "3.2 GB", "value": total},
                {"title": "Small business", "subtitle": "870.4 MB", "value": 412},
            ])
        return WidgetData(
            primary={"label": "Documents", "value": total},
            secondary=[{"label": "Size", "value": "3.2 GB"}, {"label": "In the trash", "value": 4}],
            metrics={"documents": float(total)},
        )


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


ADAPTER = PapraAdapter()
