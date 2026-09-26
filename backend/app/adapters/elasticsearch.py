"""Elasticsearch and OpenSearch: the cluster's health, its indices and its nodes.

Measured on 26.09.2026 against Elasticsearch 9.5.3 and OpenSearch 3.8.0, each
a single node with its security switched on, with invented indices: one
green, one with a replica (yellow, one node has nowhere to put it), one
closed, and on Elasticsearch one whose shard may only live on a node that
does not exist (red). OpenSearch was forked from Elasticsearch 7.10, and the
four calls the cards make answer the same on both: ``/``, ``/_cluster/health``,
``/_cluster/stats``, ``/_cat/indices`` and ``/_cat/nodes``.

⚠️ Everything under ``_cat`` comes as strings, numbers included, and a closed
index has ``null`` for its documents and its size. Elasticsearch 9.5 calls
a closed index green.

⚠️ Yellow on a single data node never clears: a replica may not sit on the
node that holds its primary, and there is no other. The cards say so and
stay calm instead of standing there amber for good. Red means a primary
has nowhere to go, and that stays red.

⚠️ Elasticsearch takes an API key as ``Authorization: ApiKey <encoded>``,
the ``encoded`` value its own answer hands out; OpenSearch has none and
signs in with a user. A wrong key is 401 with a JSON reason, and on
OpenSearch a wrong password is 401 with the plain text "Unauthorized".

⚠️ A key or user without the right is 403 ``security_exception``, and the
reason names the action: "action [cluster:monitor/health] is unauthorized"
on Elasticsearch, "no permissions for [cluster:monitor/health]" on
OpenSearch. The cluster privilege ``monitor`` and the index privilege
``monitor`` are all the cards need; the refusal passes the action on.

⚠️ Elasticsearch leaves hidden indices (``.ds-…``) out of ``_cat/indices``
unless asked with ``expand_wildcards=all``. OpenSearch lists its own
dotted indices (``.opendistro_security``, ``.plugins-ml-config``) either
way, so a dotted name counts as a system index on both.
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
    human_bytes,
    part_on,
)

PRIVILEGE_HINT = "Give it the cluster privilege monitor and the index privilege monitor on every index."
HEALTH = {"green": "ok", "yellow": "warn", "red": "bad"}
WORD = {"green": "Green", "yellow": "Yellow", "red": "Red"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
#: The action a refusal names, in either product's words.
REFUSED_ACTION = re.compile(r"(?:action \[|no permissions for \[)([^\]]+)\]")
LONELY = "Replicas have nowhere to go on a single node."


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _count(value: float) -> str:
    """Documents, shortened the way a card has room for."""
    for limit, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if value >= limit:
            return f"{value / limit:.1f}{unit}"
    return f"{value:.0f}"


def _reason(answer: Any) -> str:
    if isinstance(answer, dict):
        error = answer.get("error")
        if isinstance(error, dict):
            return " ".join(str(error.get("reason") or error.get("type") or "").split())[:300]
        if isinstance(error, str):
            return error[:300]
    return ""


class ElasticsearchAdapter(Adapter):
    kind = "elasticsearch"
    label = "Elasticsearch"
    category = "hosts"
    description = "Elasticsearch or OpenSearch: the cluster's health, its indices with the troubled ones first, and its nodes."
    icon = "elasticsearch"
    beta = False
    docs_url = "https://www.elastic.co/docs/api/doc/elasticsearch/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://elasticsearch:9200"),
        Field("api_key", "API key", type="password", secret=True,
              help="Elasticsearch only: the encoded value of a key with the cluster privilege monitor and the index privilege monitor. "
                   "Leave empty when signing in with a user, or when security is switched off."),
        Field("username", "Username", help="For OpenSearch, or Elasticsearch without an API key. Give the user the cluster and index privilege monitor."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False,
              help="Both ship with a certificate of their own making."),
    )
    widgets = (
        WidgetType(kind="cluster", label="Cluster health",
                   description="Green, yellow or red, with the nodes, indices, documents, size and the shards that have no home.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("unassigned_shards", "documents"),
                   parts=(("nodes", "Nodes"), ("indices", "Indices"), ("documents", "Documents"), ("size", "Size"),
                          ("unassigned", "Unassigned shards"), ("active", "Active shards"))),
        WidgetType(kind="indices", label="Indices",
                   description="Every index with its health, documents and size, red and yellow first, then the largest.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   options=(Field("show_system", "Show system indices", type="bool", default=False,
                                  help="Those whose name starts with a dot, and Elasticsearch's hidden ones."),
                            Field("limit", "Entries", type="number", default=10))),
        WidgetType(kind="nodes", label="Nodes",
                   description="Every node with its disk, heap and processor, the one that leads marked.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   parts=(("heap", "Heap"), ("cpu", "Processor"), ("disk", "Disk"))),
    )

    # -- talking to the cluster ----------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        key = str(config.get("api_key") or "").strip()
        user = str(config.get("username") or "").strip()
        if key and user:
            raise AdapterError("An API key and a user are both filled in.", code="two_ways_in",
                               hint="Keep one of them: the key for Elasticsearch, the user for OpenSearch.")
        # Pasted with the word in front, as the documentation writes the header.
        key = key.removeprefix("ApiKey ").strip()
        response = await ctx.request("GET", f"{base_url(config)}{path}", params=params,
                                     headers={"Authorization": f"ApiKey {key}"} if key else None,
                                     auth=(user, str(config.get("password") or "")) if user else None,
                                     verify=not config.get("insecure"), timeout=15.0, cache_seconds=cache, auth_errors=False)
        try:
            answer: Any = response.json()
        except ValueError:
            answer = None
        if response.status_code == 401:
            if not key and not user:
                raise AuthFailed("The cluster asks for sign-in. Add an API key or a user.")
            raise AuthFailed("The cluster rejected the API key." if key else "The cluster rejected the user or the password.")
        if response.status_code == 403:
            found = REFUSED_ACTION.search(_reason(answer))
            what = f" {found.group(1)}" if found else ""
            raise AdapterError(f"The cluster refuses the right{what}.", code="forbidden", hint=PRIVILEGE_HINT)
        if response.status_code >= 400:
            said = _reason(answer)
            raise AdapterError(f"The cluster refused: {said}" if said else f"The cluster answered with HTTP {response.status_code}.",
                               code="http_error")
        if answer is None:
            raise AdapterError("This address answers with something other than Elasticsearch or OpenSearch.", code="not_elasticsearch",
                               hint="Enter the address of the cluster's HTTP port, 9200 by default.")
        return answer

    async def _health(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        health = await self._get(config, ctx, "/_cluster/health")
        if not isinstance(health, dict) or "status" not in health:
            raise AdapterError("This address answers, but not the way Elasticsearch or OpenSearch do.", code="not_elasticsearch")
        return health

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        root = await self._get(config, ctx, "/", cache=0)
        version = root.get("version") if isinstance(root, dict) else None
        if not isinstance(version, dict) or not version.get("number"):
            raise AdapterError("This address answers, but not the way Elasticsearch or OpenSearch do.", code="not_elasticsearch")
        product = "OpenSearch" if version.get("distribution") == "opensearch" else "Elasticsearch"
        health = await self._health(config, ctx)
        return (f"{product} {version['number']} answers; cluster {root.get('cluster_name') or '?'} is "
                f"{str(health.get('status') or '?')}, with {int(_number(health.get('number_of_nodes')))} node(s).")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "nodes":
            nodes = await self._get(config, ctx, "/_cat/nodes", params={
                "format": "json", "bytes": "b", "h": "name,node.role,master,heap.percent,cpu,load_1m,disk.used_percent,version"})
            return self._node_rows(nodes if isinstance(nodes, list) else [], options)
        health = await self._health(config, ctx)
        if widget_kind == "indices":
            show_system = options.get("show_system") is True
            params = {"format": "json", "bytes": "b", "h": "health,status,index,docs.count,store.size,pri,rep"}
            if show_system:
                params["expand_wildcards"] = "all"
            indices = await self._get(config, ctx, "/_cat/indices", params=params, cache=30)
            return self._index_rows(indices if isinstance(indices, list) else [], health, show_system=show_system,
                                    limit=int(_number(options.get("limit")) or 10))
        stats = await self._get(config, ctx, "/_cluster/stats", cache=60) if any(
            part_on(options, part) for part in ("indices", "documents", "size")) else {}
        return self._cluster(health, stats if isinstance(stats, dict) else {})

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _lonely(health: dict[str, Any]) -> bool:
        """Yellow on one data node, with every primary placed: it never gets greener."""
        return (str(health.get("status")) == "yellow" and int(_number(health.get("number_of_data_nodes"))) <= 1
                and int(_number(health.get("unassigned_primary_shards"))) == 0)

    @classmethod
    def _cluster(cls, health: dict[str, Any], stats: dict[str, Any]) -> WidgetData:
        colour = str(health.get("status") or "")
        indices = stats.get("indices") if isinstance(stats.get("indices"), dict) else {}
        documents = _number((indices.get("docs") or {}).get("count"))
        unassigned = int(_number(health.get("unassigned_shards")))
        lonely = cls._lonely(health)
        secondary = [
            {"label": "Nodes", "value": int(_number(health.get("number_of_nodes"))), "part": "nodes"},
            {"label": "Indices", "value": int(_number(indices.get("count"))), "part": "indices"},
            {"label": "Documents", "value": _count(documents), "part": "documents"},
            {"label": "Size", "value": human_bytes(_number((indices.get("store") or {}).get("size_in_bytes"))), "part": "size"},
            {"label": "Unassigned shards", "value": unassigned, "part": "unassigned"},
            {"label": "Active shards", "value": f"{_number(health.get('active_shards_percent_as_number')):.0f} %", "part": "active"},
        ]
        return WidgetData(
            status="ok" if lonely else HEALTH.get(colour, "unknown"),
            primary={"label": "Cluster health", "value": WORD.get(colour, colour.capitalize() or "?")},
            secondary=secondary,
            meta={"status_reason": LONELY if lonely else ""},
            metrics={"unassigned_shards": float(unassigned), "documents": documents},
        )

    @classmethod
    def _index_rows(cls, indices: list[Any], health: dict[str, Any], *, show_system: bool, limit: int) -> WidgetData:
        single = int(_number(health.get("number_of_data_nodes"))) <= 1
        rows = []
        for index in indices:
            if not isinstance(index, dict):
                continue
            name = str(index.get("index") or "?")
            if name.startswith(".") and not show_system:
                continue
            if index.get("status") == "close":
                rows.append({"title": name, "subtitle": "Closed", "status": "unknown", "size": -1.0, "closed": True})
                continue
            colour = str(index.get("health") or "")
            status = HEALTH.get(colour, "unknown")
            size = _number(index.get("store.size"))
            documents = _number(index.get("docs.count"))
            # A red index whose primary found no home has no count at all.
            parts = [] if index.get("docs.count") is None else ["1 document" if documents == 1 else f"{_count(documents)} documents"]
            if colour == "yellow" and single:
                # ⚠️ Its replica can never be placed; nothing is wrong with it.
                status = "ok"
                parts.insert(0, "No room for a replica")
            elif colour == "red":
                parts.insert(0, "Red, a primary shard has no home")
            elif colour != "green":
                parts.insert(0, WORD.get(colour, colour.capitalize() or "Unknown"))
            rows.append({"title": name, "subtitle": " · ".join(parts), "value": human_bytes(size) if index.get("store.size") is not None else "",
                         "status": status, "size": size})
        # Closed ones last: neither healthy nor broken, and nothing to look at.
        rows.sort(key=lambda row: (row.get("closed", False), ORDER.get(row["status"], 9), -row["size"], row["title"]))
        for row in rows:
            row.pop("size")
            row.pop("closed", None)
        troubled = [row for row in rows if row["status"] in ("bad", "warn")]
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if troubled else "ok" if rows else "unknown",
            items=rows[:max(1, limit)],
            meta={"empty": "No index yet." if show_system else "No index yet, apart from system indices."},
        )

    @staticmethod
    def _node_rows(nodes: list[Any], options: dict[str, Any]) -> WidgetData:
        rows = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            disk = _number(node.get("disk.used_percent"))
            heap = _number(node.get("heap.percent"))
            # The watermarks both products start from: 85 stops new shards, 90 moves them away, 95 blocks writing.
            status = "bad" if disk >= 90 else "warn" if disk >= 85 or heap >= 90 else "ok"
            parts = []
            if node.get("master") == "*":
                parts.append("Leads the cluster")
            if part_on(options, "disk"):
                parts.append(f"Disk {disk:.0f} %")
            if part_on(options, "heap"):
                parts.append(f"Heap {heap:.0f} %")
            if part_on(options, "cpu"):
                parts.append(f"CPU {_number(node.get('cpu')):.0f} %")
            rows.append({"title": str(node.get("name") or "?"), "subtitle": " · ".join(parts),
                         "value": str(node.get("version") or ""), "status": status})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"]))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if any(row["status"] == "warn" for row in rows)
            else "ok" if rows else "unknown",
            items=rows,
            meta={"empty": "The cluster lists no node."},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        red = fake.flicker("elasticsearch-red", tick, 0.2)
        health = {"status": "red" if red else "green", "number_of_nodes": 3, "number_of_data_nodes": 3,
                  "unassigned_shards": 1 if red else 0, "unassigned_primary_shards": 1 if red else 0,
                  "active_shards_percent_as_number": 97.5 if red else 100.0}
        if widget_kind == "cluster":
            return self._cluster(health, {"indices": {"count": 14, "docs": {"count": 18_400_000 + tick * 1200},
                                                      "store": {"size_in_bytes": 41_800_000_000}}})
        if widget_kind == "nodes":
            return self._node_rows([
                {"name": "es-1", "master": "*", "disk.used_percent": "61.2", "heap.percent": "48", "cpu": "12", "version": "9.5.3"},
                {"name": "es-2", "master": "-", "disk.used_percent": "58.9", "heap.percent": "52", "cpu": "9", "version": "9.5.3"},
                {"name": "es-3", "master": "-", "disk.used_percent": "86.4", "heap.percent": "44", "cpu": "15", "version": "9.5.3"},
            ], options)
        indices = [
            {"health": "green", "status": "open", "index": "logs-web-2026.09", "docs.count": "12400000", "store.size": "28700000000"},
            {"health": "green", "status": "open", "index": "metrics-home", "docs.count": "5900000", "store.size": "11200000000"},
            {"health": "red" if red else "green", "status": "open", "index": "paperless", "docs.count": "4200", "store.size": "96000000"},
            {"health": "green", "status": "open", "index": "immich-search", "docs.count": "81000", "store.size": "1200000000"},
            {"health": "green", "status": "close", "index": "logs-web-2025.12", "docs.count": None, "store.size": None},
            {"health": "green", "status": "open", "index": ".security-7", "docs.count": "12", "store.size": "90000"},
        ]
        return self._index_rows(indices, health, show_system=options.get("show_system") is True,
                                limit=int(_number(options.get("limit")) or 10))


ADAPTER = ElasticsearchAdapter()
