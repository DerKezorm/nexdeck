"""Meilisearch, against the answers of a live Meilisearch 1.53.2 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

MS = "http://meilisearch.example.com"
CONFIG = {"url": MS, "api_key": "made-up-key"}
NO_PRIMARY_KEY = ("The primary key inference failed as the engine did not find any field ending with `id` in its name. "
                  "Please specify the primary key manually using the `primaryKey` query parameter.")


def index(documents: int, indexing: bool = False) -> dict[str, Any]:
    return {"numberOfDocuments": documents, "indexSize": 73728, "usedIndexSize": 40960, "rawDocumentDbSize": 4096, "avgDocumentSize": 155,
            "isIndexing": indexing, "numberOfEmbeddings": 0, "numberOfEmbeddedDocuments": 0, "fieldDistribution": {}}


def task(uid: int, index_uid: str, status: str, error: str | None = None) -> dict[str, Any]:
    return {"uid": uid, "batchUid": uid, "indexUid": index_uid, "status": status, "type": "documentAdditionOrUpdate", "canceledBy": None,
            "details": {"receivedDocuments": 1, "indexedDocuments": 0 if error else 1},
            "error": {"message": error, "code": "index_primary_key_no_candidate_found", "type": "invalid_request"} if error else None,
            "duration": "PT0.007647446S", "enqueuedAt": "2026-09-11T10:58:07.341358886Z", "finishedAt": "2026-09-11T10:58:07.396164721Z"}


STATS = {"databaseSize": 413696, "usedDatabaseSize": 196608, "lastUpdate": "2026-09-11T10:58:07.388686441Z",
         "indexes": {"books": index(25), "broken": index(0), "movies": index(7)}}
#: Newest first, as the live server listed them.
FAILED_ONCE = [task(2, "broken", "failed", NO_PRIMARY_KEY), task(1, "movies", "succeeded"), task(0, "books", "succeeded")]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(stats: dict[str, Any], tasks: list[dict[str, Any]]) -> tuple[respx.Route, respx.Route]:
    stats_route = respx.get(f"{MS}/stats").mock(return_value=httpx.Response(200, json=stats))
    tasks_route = respx.get(f"{MS}/tasks").mock(return_value=httpx.Response(200, json={"results": tasks, "total": len(tasks), "limit": 50, "from": 4, "next": None}))
    return stats_route, tasks_route


@respx.mock
async def test_an_index_whose_last_task_failed_comes_first_with_the_reason(ctx: Context) -> None:
    stats_route, tasks_route = _server(STATS, FAILED_ONCE)
    data = await get_adapter("meilisearch").fetch("indexes", CONFIG, {"limit": 10}, ctx)
    assert stats_route.calls.last.request.headers["Authorization"] == "Bearer made-up-key"
    assert dict(tasks_route.calls.last.request.url.params) == {"statuses": "succeeded,failed", "limit": "50"}
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [("broken", "bad", "0"), ("books", "ok", "25"), ("movies", "ok", "7")]
    assert data.items[0]["subtitle"].startswith("Failed · The primary key inference failed")
    assert data.secondary == [{"label": "Indexes", "value": 3}, {"label": "Failed", "value": 1}] and data.status == "bad"


@respx.mock
async def test_an_old_failure_does_not_keep_an_index_red(ctx: Context) -> None:
    """Measured: both failed tasks stayed in the list after the third batch went through."""
    recovered = {**STATS, "indexes": {**STATS["indexes"], "broken": index(1)}}
    _server(recovered, [task(4, "broken", "succeeded"), task(3, "broken", "failed", "Document identifier `now with a key` is invalid."),
                        *FAILED_ONCE])
    data = await get_adapter("meilisearch").fetch("indexes", CONFIG, {"limit": 10}, ctx)
    assert {row["title"]: row["status"] for row in data.items} == {"books": "ok", "movies": "ok", "broken": "ok"}
    assert data.status == "ok" and data.secondary == [{"label": "Indexes", "value": 3}]


@respx.mock
async def test_an_index_that_is_indexing(ctx: Context) -> None:
    _server({**STATS, "indexes": {"books": index(25, indexing=True)}}, [])
    data = await get_adapter("meilisearch").fetch("indexes", CONFIG, {"limit": 10}, ctx)
    assert (data.items[0]["status"], data.items[0]["subtitle"]) == ("warn", "Indexing")


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    _server(STATS, FAILED_ONCE)
    data = await get_adapter("meilisearch").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Documents", "value": 32}
    assert data.secondary == [{"label": "Indexes", "value": 3}, {"label": "Database", "value": "404.0 KB"}, {"label": "Failed", "value": 1}]
    assert data.metrics == {"documents": 32.0} and data.status == "bad"


@respx.mock
async def test_a_missing_key_and_a_key_without_the_right(ctx: Context) -> None:
    respx.get(f"{MS}/stats").mock(return_value=httpx.Response(401, json={"code": "missing_authorization_header", "type": "auth"}))
    with pytest.raises(AuthFailed, match="wants an API key"):
        await get_adapter("meilisearch").fetch("summary", CONFIG, {}, ctx)
    # Measured: the default search key gets the same answer as a wrong key.
    respx.get(f"{MS}/stats").mock(return_value=httpx.Response(403, json={"message": "The provided API key is invalid.", "code": "invalid_api_key"}))
    with pytest.raises(AuthFailed, match="search key is not enough"):
        await get_adapter("meilisearch").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))


@respx.mock
async def test_the_connection_test_and_something_else_at_the_address(ctx: Context) -> None:
    respx.get(f"{MS}/version").mock(return_value=httpx.Response(200, json={"commitSha": "made-up", "commitDate": "unknown", "pkgVersion": "1.53.2"}))
    _server(STATS, [])
    assert await get_adapter("meilisearch").test(CONFIG, ctx) == "Meilisearch 1.53.2 answers with 3 indexes."
    respx.get(f"{MS}/stats").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("meilisearch").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert other.value.code == "not_meilisearch"
