"""Meilisearch: how many documents each index holds, and whether its last indexing failed.

Measured against Meilisearch 1.53.2 on 11.09.2026, in production mode with a
master key: two indexes with documents, and a third whose first batch had no
field to take as the primary key and whose second had an invalid id, before a
third batch went through.

⚠️ A key without the right answers exactly like a wrong one: 403
``invalid_api_key``, "The provided API key is invalid." The default search
key gets that on ``/stats``. Only a missing key says what is missing (401).

⚠️ The "Default Read-Only Admin API Key" reads the statistics, and it reads
every other key as well, the admin key included. The field asks for a key of
its own that may read statistics, indexes, tasks and the version.

⚠️ A failed task stays in the task list after the index has indexed fine
again. The cards judge each index by its latest finished task, so an old
failure does not keep it red.
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
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
)

#: The latest finished tasks are enough to know how each index last ended.
TASKS_TO_READ = 50


class MeilisearchAdapter(Adapter):
    kind = "meilisearch"
    label = "Meilisearch"
    category = "hosts"
    description = "How many documents each index holds, and whether its last indexing failed."
    icon = "meilisearch"
    beta = False
    docs_url = "https://www.meilisearch.com/docs/reference/api/stats"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://meilisearch:7700"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key of its own with the actions stats.get, indexes.get, tasks.get and version. "
                   "The default read-only admin key works too, but it can read every other key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="indexes", label="Indexes", description="Every index with its documents, failed and indexing ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("documents",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Search", description="Documents across all indexes, the size of the database and failed indexes.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("documents",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("Meilisearch wants an API key.")
        if response.status_code == 403:
            raise AuthFailed("Meilisearch refused the API key. A search key is not enough; the key needs stats.get, indexes.get, tasks.get and version.")
        if response.status_code >= 400:
            raise AdapterError(f"Meilisearch answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Meilisearch did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Meilisearch.") from error

    async def _state(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        stats = await self._json(config, ctx, "/stats")
        if not isinstance(stats, dict) or not isinstance(stats.get("indexes"), dict):
            raise AdapterError("This address answers, but not the way Meilisearch does.", code="not_meilisearch")
        tasks = await self._json(config, ctx, "/tasks", {"statuses": "succeeded,failed", "limit": TASKS_TO_READ})
        found = tasks.get("results") if isinstance(tasks, dict) else None
        return stats, [one for one in found or [] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._json(config, ctx, "/version", cache=0)
        stats, _tasks = await self._state(config, ctx)
        number = version.get("pkgVersion", "?") if isinstance(version, dict) else "?"
        return f"Meilisearch {number} answers with {len(stats['indexes'])} indexes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        stats, tasks = await self._state(config, ctx)
        rows = self._rows(stats, tasks)
        if widget_kind == "summary":
            return self._summary(stats, rows)
        return self._indexes(rows, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _rows(stats: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        # Newest first, as measured: the first task seen for an index is its last one.
        for task in tasks:
            latest.setdefault(str(task.get("indexUid") or ""), task)
        rows = []
        for name, index in sorted(stats["indexes"].items()):
            index = index if isinstance(index, dict) else {}
            documents = int(index.get("numberOfDocuments") or 0)
            last = latest.get(name, {})
            if last.get("status") == "failed":
                error = last.get("error") if isinstance(last.get("error"), dict) else {}
                state, word, reason = "bad", "Failed", " ".join(str(error.get("message") or "").split())
            elif index.get("isIndexing"):
                state, word, reason = "warn", "Indexing", ""
            else:
                state, word, reason = "ok", "", ""
            rows.append({"state": state, "documents": documents, "row": {
                "title": name,
                "subtitle": " · ".join(part for part in (word, reason[:120]) if part),
                "status": state,
                "value": str(documents),
            }})
        return rows

    @staticmethod
    def _indexes(rows: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        order = {"bad": 0, "warn": 1, "ok": 2}
        ranked = sorted(rows, key=lambda one: (order.get(one["state"], 9), -one["documents"], one["row"]["title"]))
        failed = sum(1 for one in rows if one["state"] == "bad")
        documents = sum(one["documents"] for one in rows)
        return WidgetData(
            status="bad" if failed else "ok",
            items=[one["row"] for one in ranked][: int(options.get("limit") or 10)],
            secondary=[{"label": "Indexes", "value": len(rows)}] + ([{"label": "Failed", "value": failed}] if failed else []),
            meta={"empty": "No indexes yet."},
            metrics={"documents": float(documents)},
        )

    @staticmethod
    def _summary(stats: dict[str, Any], rows: list[dict[str, Any]]) -> WidgetData:
        failed = sum(1 for one in rows if one["state"] == "bad")
        documents = sum(one["documents"] for one in rows)
        secondary: list[dict[str, Any]] = [{"label": "Indexes", "value": len(rows)}]
        if stats.get("databaseSize") is not None:
            secondary.append({"label": "Database", "value": human_bytes(stats.get("databaseSize"))})
        if failed:
            secondary.append({"label": "Failed", "value": failed})
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Documents", "value": documents},
            secondary=secondary,
            metrics={"documents": float(documents)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        indexing = fake.flicker("meili-indexing", tick, 0.6)
        stats = {"databaseSize": 1_734_000_000, "indexes": {
            "karakeep-bookmarks": {"numberOfDocuments": 4_120 + tick % 7, "isIndexing": indexing},
            "paperless": {"numberOfDocuments": 18_932, "isIndexing": False},
            "recipes": {"numberOfDocuments": 212, "isIndexing": False},
        }}
        tasks = [{"indexUid": "recipes", "status": "failed", "error": {"message": "Document identifier `pasta carbonara` is invalid."}}] \
            if fake.flicker("meili-failed", tick, 0.8) else []
        rows = self._rows(stats, tasks)
        if widget_kind == "summary":
            return self._summary(stats, rows)
        return self._indexes(rows, options)


ADAPTER = MeilisearchAdapter()
