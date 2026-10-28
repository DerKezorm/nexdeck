"""Garage: the cluster, its nodes, its buckets and how full they are.

Garage is an S3 store for a few machines at home. Its admin API sits on its
own port (3903) and takes the admin token as a bearer token. Two generations
answer there, and they were both measured on 27.10.2026 (Garage 2.1.0 and
1.3.1, one node each):

* Garage 2 has ``/v2/GetClusterHealth``, ``/v2/GetClusterStatus``,
  ``/v2/GetClusterLayout``, ``/v2/ListBuckets`` and ``/v2/GetBucketInfo``.
* Garage 1 has ``/v1/health``, ``/v1/status``, ``/v1/layout``,
  ``/v1/bucket?list`` and ``/v1/bucket?id=``, with nearly the same bodies.

⚠️ Garage 1 answers a ``/v2`` path with **400** ``Unknown API endpoint``, not
404, and Garage 2.1 answers a ``/v1`` path the same way. The generation is
therefore decided by that message, once per connection, and remembered.

⚠️ A bucket's size and quota are not in the list. Each bucket costs one more
call to its own info, so the cards read at most ``MAX_BUCKETS`` of them, in the
order Garage lists them. The count of buckets is the full one.
``GetClusterStatistics`` is a text for a terminal and not read at all.
"""

from __future__ import annotations

import asyncio
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
    path_segment,
    percent,
    status_from_percent,
)

#: How many buckets are looked into one by one.
MAX_BUCKETS = 40
#: How many of those calls run at once.
PARALLEL = 6

PATHS = {
    "v2": {"health": "/v2/GetClusterHealth", "status": "/v2/GetClusterStatus", "layout": "/v2/GetClusterLayout",
           "buckets": "/v2/ListBuckets"},
    "v1": {"health": "/v1/health", "status": "/v1/status", "layout": "/v1/layout", "buckets": "/v1/bucket?list"},
}

STATUS_WORDS = {"healthy": "Healthy", "degraded": "Degraded", "unavailable": "Unavailable"}


def _wrong_generation(response: Any) -> bool:
    """Whether an answer says "this API does not exist here" rather than "no"."""
    if response.status_code not in (400, 404):
        return False
    return "unknown api endpoint" in response.text.lower() or response.status_code == 404


class GarageAdapter(Adapter):
    kind = "garage"
    label = "Garage"
    category = "nas"
    description = "The Garage cluster, its nodes, its buckets and how full they are."
    icon = "garage"
    docs_url = "https://garagehq.deuxfleurs.fr/documentation/reference-manual/admin-api/"
    #: Measured against Garage 2.1.0 and 1.3.1 on 27.10.2026, one node each; it stays beta until somebody confirms it on a cluster in use.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://garage:3903",
              help="The admin API, port 3903 unless you changed it, not the S3 port."),
        Field("token", "Admin token", type="password", secret=True, required=True,
              help="admin_token in the [admin] section of garage.toml, or a token made with garage admin-token create."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In garage.toml, the [admin] section needs api_bind_addr and an admin_token.",
        "Publish the admin port to your own network only; the token can change the whole cluster, and nexdeck only reads.",
    )
    widgets = (
        WidgetType(
            kind="cluster",
            label="Cluster",
            description="Whether Garage is healthy, how many storage nodes are up, and a layout change that waits to be applied.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("nodes_up", "partitions_short"),
        ),
        WidgetType(
            kind="nodes",
            label="Nodes",
            description="Every node with its zone, its capacity and the free space of its data disk, those that are down first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
        ),
        WidgetType(
            kind="buckets",
            bars=True,
            label="Buckets",
            description="Every bucket with its objects, its size and, where there is a quota, how much of it is used.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="storage",
            label="Storage used",
            description="What all buckets hold together, and the free space on the data disks.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("stored_bytes", "objects"),
        ),
    )

    def _body(self, response: Any) -> Any:
        if response.status_code >= 400:
            raise AdapterError(f"Garage answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the admin API, port 3903 unless you changed it.")
        try:
            body = response.json()
        except ValueError as error:
            raise AdapterError("Garage did not answer with JSON.", code="not_json",
                               hint="The URL probably points at the S3 port or a proxy, not at the admin API.") from error
        return body

    async def _generation(self, config: dict[str, Any], ctx: Context) -> str:
        """Which calls this Garage speaks, found by asking for its health once."""
        known = ctx.cache.get("garage.generation")
        if known:
            return known
        for generation in ("v2", "v1"):
            response = await ctx.request(
                "GET", f"{base_url(config)}{PATHS[generation]['health']}",
                headers={"Authorization": f"Bearer {config.get('token') or ''}"},
                verify=not config.get("insecure"),
            )
            if _wrong_generation(response):
                continue
            if response.status_code >= 400:
                raise AdapterError(f"Garage answered with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; it is the address of the admin API, port 3903 unless you changed it.")
            ctx.cache["garage.generation"] = generation
            return generation
        raise AdapterError("Garage's admin API did not answer to either generation of calls.", code="no_admin_api",
                           hint="Check the URL: it is the admin API (port 3903), not the S3 port, and Garage 1.0 or newer.")

    async def _get(self, config: dict[str, Any], ctx: Context, name: str, cache: float = 20) -> Any:
        for _attempt in range(2):
            generation = await self._generation(config, ctx)
            response = await ctx.request(
                "GET", f"{base_url(config)}{PATHS[generation][name]}",
                headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
                verify=not config.get("insecure"), cache_seconds=cache,
            )
            if _wrong_generation(response):
                # ⚠️ Garage was updated from 1 to 2 (or back) since the choice was made.
                ctx.cache.pop("garage.generation", None)
                continue
            return self._body(response)
        raise AdapterError("Garage's admin API did not answer to either generation of calls.", code="no_admin_api",
                           hint="Check the URL: it is the admin API (port 3903), not the S3 port, and Garage 1.0 or newer.")

    async def _bucket(self, config: dict[str, Any], ctx: Context, generation: str, bucket_id: str) -> dict[str, Any]:
        bucket_id = path_segment(bucket_id, "The bucket")
        path = f"/v2/GetBucketInfo?id={bucket_id}" if generation == "v2" else f"/v1/bucket?id={bucket_id}"
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=120,
        )
        body = self._body(response)
        return body if isinstance(body, dict) else {}

    async def _buckets(self, config: dict[str, Any], ctx: Context) -> tuple[list[dict[str, Any]], int]:
        """Every bucket looked into, and how many there are in all."""
        generation = await self._generation(config, ctx)
        listed = await self._get(config, ctx, "buckets", cache=60)
        rows = [row for row in listed if isinstance(row, dict) and row.get("id")] if isinstance(listed, list) else []
        gate = asyncio.Semaphore(PARALLEL)

        async def one(row: dict[str, Any]) -> dict[str, Any]:
            async with gate:
                info = await self._bucket(config, ctx, generation, str(row["id"]))
            aliases = row.get("globalAliases") or []
            return {**info, "name": aliases[0] if aliases else str(row["id"])[:12]}

        return list(await asyncio.gather(*(one(row) for row in rows[:MAX_BUCKETS]))), len(rows)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        health = await self._get(config, ctx, "health", cache=0)
        status = await self._get(config, ctx, "status", cache=0)
        version = next((str(node.get("garageVersion")) for node in (status or {}).get("nodes") or []
                        if isinstance(node, dict) and node.get("garageVersion")), "")
        up, total = _nodes_up(health)
        return f"Garage {version or '?'} answers, {up} of {total} storage nodes up."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        status = await self._get(config, ctx, "status", cache=0)
        for node in (status or {}).get("nodes") or []:
            if isinstance(node, dict) and node.get("garageVersion"):
                return str(node["garageVersion"]).lstrip("v")
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "nodes":
            return self._nodes(await self._get(config, ctx, "status"))
        if widget_kind in ("buckets", "storage"):
            buckets, total = await self._buckets(config, ctx)
            if widget_kind == "buckets":
                return self._bucket_list(buckets, total, options)
            return self._storage(buckets, total, await self._get(config, ctx, "status"))
        health = await self._get(config, ctx, "health")
        layout = await self._get(config, ctx, "layout")
        return self._cluster(health, layout)

    def _cluster(self, health: dict[str, Any], layout: dict[str, Any]) -> WidgetData:
        word = str((health or {}).get("status") or "")
        up, total = _nodes_up(health)
        short = max(0, int((health or {}).get("partitions") or 0) - int((health or {}).get("partitionsAllOk") or 0))
        waiting = len((layout or {}).get("stagedRoleChanges") or []) if isinstance(layout, dict) else 0
        secondary = [
            {"label": "Status", "value": STATUS_WORDS.get(word, word.capitalize() or "Unknown")},
            {"label": "Storage nodes", "value": total},
        ]
        if short:
            secondary.append({"label": "Partitions short of copies", "value": short})
        if waiting:
            secondary.append({"label": "Layout changes waiting", "value": waiting})
        status = "ok" if word == "healthy" else "warn" if word == "degraded" else "bad"
        if status == "ok" and waiting:
            status = "warn"
        return WidgetData(
            status=status,
            primary={"label": "Nodes up", "value": up},
            secondary=secondary,
            metrics={"nodes_up": float(up), "partitions_short": float(short)},
        )

    def _nodes(self, status: dict[str, Any]) -> WidgetData:
        items = []
        for node in (status or {}).get("nodes") or []:
            if not isinstance(node, dict):
                continue
            role = node.get("role") if isinstance(node.get("role"), dict) else None
            up = bool(node.get("isUp"))
            disk = node.get("dataPartition") if isinstance(node.get("dataPartition"), dict) else {}
            free = disk.get("available")
            share = percent(disk.get("total") - free, disk.get("total")) if free is not None and disk.get("total") else None
            state = "bad" if not up else "warn" if node.get("draining") else (status_from_percent(share) if share is not None else "ok")
            parts = [
                f"Zone {role['zone']}" if role and role.get("zone") else "No role",
                human_bytes(role["capacity"]) if role and role.get("capacity") else "",
                f"{human_bytes(free)} free" if free is not None else "",
            ]
            items.append({
                "title": str(node.get("hostname") or str(node.get("id") or "?")[:12]),
                "subtitle": " · ".join(part for part in parts if part),
                "status": state,
                "value": "Down" if not up else "Draining" if node.get("draining") else "Up",
            })
        order = {"bad": 0, "warn": 1, "ok": 2}
        items.sort(key=lambda entry: order[entry["status"]])
        states = {entry["status"] for entry in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items,
            secondary=[{"label": "Storage nodes", "value": len(items)}],
        )

    def _bucket_list(self, buckets: list[dict[str, Any]], total: int, options: dict[str, Any]) -> WidgetData:
        items = []
        for bucket in buckets:
            size = int(bucket.get("bytes") or 0)
            quotas = bucket.get("quotas") if isinstance(bucket.get("quotas"), dict) else {}
            ceiling = quotas.get("maxSize")
            used = percent(size, ceiling) if ceiling else None
            objects_used = percent(bucket.get("objects"), quotas.get("maxObjects")) if quotas.get("maxObjects") else None
            share = max((one for one in (used, objects_used) if one is not None), default=None)
            items.append({
                "title": bucket["name"],
                "subtitle": f"{human_bytes(size)} of {human_bytes(ceiling)}" if ceiling else human_bytes(size),
                "status": status_from_percent(share) if share is not None else "ok",
                "value": int(bucket.get("objects") or 0),
            })
        order = {"bad": 0, "warn": 1, "ok": 2}
        items.sort(key=lambda entry: (order[entry["status"]], -entry["value"]))
        states = {entry["status"] for entry in items}
        limit = int(options.get("limit") or 10)
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items[:limit],
            secondary=[{"label": "Buckets", "value": total}],
        )

    def _storage(self, buckets: list[dict[str, Any]], total: int, status: dict[str, Any]) -> WidgetData:
        size = sum(int(bucket.get("bytes") or 0) for bucket in buckets)
        objects = sum(int(bucket.get("objects") or 0) for bucket in buckets)
        disks = [node["dataPartition"] for node in (status or {}).get("nodes") or []
                 if isinstance(node, dict) and isinstance(node.get("dataPartition"), dict)
                 and node["dataPartition"].get("total")]
        # The fullest data disk decides, since a node that is full refuses writes.
        fullest = max((percent(disk["total"] - disk.get("available", 0), disk["total"]) for disk in disks), default=None)
        secondary = [{"label": "Buckets", "value": total}, {"label": "Objects", "value": objects}]
        if fullest is not None:
            secondary.append({"label": "Fullest data disk", "value": fullest, "unit": "%"})
        return WidgetData(
            status=status_from_percent(fullest) if fullest is not None else "ok",
            primary={"label": "Stored", "value": human_bytes(size)},
            secondary=secondary,
            metrics={"stored_bytes": float(size), "objects": float(objects)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        down = fake.flicker("garage-node", tick, 0.1)
        nodes = [
            {"id": "a1", "hostname": "garage-1", "isUp": True, "draining": False,
             "role": {"zone": "dc1", "capacity": 4 * 1024 ** 4},
             "dataPartition": {"total": 4 * 1024 ** 4, "available": int(fake.walk("garage-d1", tick, 1.2, 1.6) * 1024 ** 4)}},
            {"id": "b2", "hostname": "garage-2", "isUp": True, "draining": False,
             "role": {"zone": "dc2", "capacity": 4 * 1024 ** 4},
             "dataPartition": {"total": 4 * 1024 ** 4, "available": int(fake.walk("garage-d2", tick, 1.1, 1.5) * 1024 ** 4)}},
            {"id": "c3", "hostname": "garage-3", "isUp": not down, "draining": False,
             "role": {"zone": "dc3", "capacity": 2 * 1024 ** 4},
             "dataPartition": {"total": 2 * 1024 ** 4, "available": int(fake.walk("garage-d3", tick, 0.5, 0.8) * 1024 ** 4)}},
        ]
        status = {"nodes": nodes}
        buckets = [
            {"name": "backups", "objects": fake.counter("garage-o1", tick, 4200, 0.4), "bytes": int(fake.walk("garage-b1", tick, 1.4, 1.5) * 1024 ** 4),
             "quotas": {"maxSize": 2 * 1024 ** 4, "maxObjects": None}},
            {"name": "media", "objects": fake.counter("garage-o2", tick, 18000, 0.1), "bytes": 3 * 1024 ** 4 // 2,
             "quotas": {"maxSize": None, "maxObjects": None}},
            {"name": "photos", "objects": fake.counter("garage-o3", tick, 61000, 0.3), "bytes": 410 * 1024 ** 3,
             "quotas": {"maxSize": 500 * 1024 ** 3, "maxObjects": None}},
            {"name": "scratch", "objects": 120, "bytes": 3 * 1024 ** 3, "quotas": {"maxSize": None, "maxObjects": 1000}},
        ]
        if widget_kind == "nodes":
            return self._nodes(status)
        if widget_kind == "buckets":
            return self._bucket_list(buckets, len(buckets), options)
        if widget_kind == "storage":
            return self._storage(buckets, len(buckets), status)
        up = 2 if down else 3
        health = {"status": "degraded" if down else "healthy", "storageNodes": 3, "storageNodesUp": up,
                  "partitions": 256, "partitionsAllOk": 256 - (86 if down else 0)}
        return self._cluster(health, {"stagedRoleChanges": []})


def _nodes_up(health: dict[str, Any]) -> tuple[int, int]:
    """Storage nodes that are up and all of them; Garage 1 calls the first ``storageNodesOk``."""
    health = health if isinstance(health, dict) else {}
    total = int(health.get("storageNodes") or 0)
    up = health.get("storageNodesUp", health.get("storageNodesOk"))
    return int(up if up is not None else 0), total


ADAPTER = GarageAdapter()
