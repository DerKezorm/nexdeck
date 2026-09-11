"""autobrr: releases grabbed from announces, and the filters that decide.

Measured against autobrr 1.86.0 on 11.09.2026. The releases were written
into the test instance's database, because a release needs an IRC network
and an indexer to arrive the ordinary way; what was measured is how the API
hands them out.

⚠️ ``/api/release/stats`` counts since the first start and never resets. A
card coloured by its error count would stay red for good after one failed
push three weeks ago, so the summary only warns about something that is
true now: no filter switched on.

⚠️ A missing key gets 403 ``Forbidden`` and a wrong one 401 ``Unauthorized``,
both as plain text.
"""

from __future__ import annotations

import time
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
    ago,
    base_url,
    human_bytes,
)

#: A release can go to several actions; the worst outcome speaks for it.
PUSH = {"PUSH_ERROR": (0, "bad", "Push failed"), "PUSH_REJECTED": (1, "warn", "Rejected"), "PUSH_APPROVED": (2, "ok", "Pushed")}


class AutobrrAdapter(Adapter):
    kind = "autobrr"
    label = "autobrr"
    category = "downloads"
    description = "Releases grabbed from announces, and the filters that decide."
    icon = "autobrr"
    beta = False
    docs_url = "https://autobrr.com/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://autobrr:7474"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > API keys > Add new."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="releases", label="Recent releases", description="The latest releases, with the filter and what the client said.",
                   renderer="list", default_size=(4, 3), refresh_seconds=60,
                   options=(Field("limit", "Entries", type="number", default=8),
                            Field("pushed_only", "Only releases that were pushed", type="bool", default=False))),
        WidgetType(kind="summary", label="Grabbed", description="Pushed releases and the filters that are switched on.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("pushed",)),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"X-API-Token": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("autobrr rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"autobrr answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of autobrr itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("autobrr did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _filters(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/filters")
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way autobrr does.", code="not_autobrr")
        return [one for one in answer if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        about = await self._get(config, ctx, "/config", cache=0)
        if not isinstance(about, dict) or "version" not in about:
            raise AdapterError("This address answers, but not the way autobrr does.", code="not_autobrr")
        filters = await self._filters(config, ctx)
        on = sum(1 for one in filters if one.get("enabled"))
        return f"autobrr {about['version']} answers with {len(filters)} filters, {on} switched on."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            stats = await self._get(config, ctx, "/release/stats")
            if not isinstance(stats, dict):
                raise AdapterError("This address answers, but not the way autobrr does.", code="not_autobrr")
            return self._summary(stats, await self._filters(config, ctx), base_url(config))
        params: dict[str, Any] = {"limit": max(1, int(options.get("limit") or 8))}
        if options.get("pushed_only"):
            params["push_status"] = "PUSH_APPROVED"
        answer = await self._get(config, ctx, "/release", params=params)
        if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
            raise AdapterError("This address answers, but not the way autobrr does.", code="not_autobrr")
        return self._releases(answer, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(stats: dict[str, Any], filters: list[dict[str, Any]], base: str) -> WidgetData:
        def count(key: str) -> int:
            return int(stats.get(key) or 0)

        on = sum(1 for one in filters if one.get("enabled"))
        return WidgetData(
            status="warn" if not on else "ok",
            primary={"label": "Pushed", "value": count("push_approved_count")},
            # ⚠️ Seen on a real board: four chips on a card two columns wide ran
            # off its edge. Rejections and errors only when there are any.
            secondary=[{"label": "Filters on", "value": on}, {"label": "Releases", "value": count("total_count")}]
            + [{"label": label, "value": count(key)} for label, key in (("Rejected", "push_rejected_count"), ("Errors", "push_error_count")) if count(key)],
            link=f"{base}/releases",
            meta={"notice": "No filter is switched on, so autobrr grabs nothing."} if not on else {},
            metrics={"pushed": float(count("push_approved_count"))},
        )

    @staticmethod
    def _releases(answer: dict[str, Any], base: str) -> WidgetData:
        items = []
        for release in answer["data"]:
            if not isinstance(release, dict):
                continue
            pushes = [push for push in release.get("action_status") or [] if isinstance(push, dict) and push.get("status") in PUSH]
            if pushes:
                _rank, status, word = min(PUSH[push["status"]] for push in pushes)
            elif release.get("filter_status") == "FILTER_REJECTED":
                status, word = "unknown", "No match"
            else:
                status, word = "unknown", ""
            indexer = release.get("indexer") if isinstance(release.get("indexer"), dict) else {}
            parts = (word, str(release.get("filter") or ""), str(indexer.get("name") or ""),
                     human_bytes(release["size"]) if release.get("size") else "")
            items.append({
                "title": str(release.get("name") or release.get("title") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "status": status,
                "value": ago(release.get("timestamp")),
            })
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Releases", "value": int(answer.get("count") or len(items))}],
            link=f"{base}/releases",
            meta={"empty": "No releases yet."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        failed = fake.flicker("ab-push", tick, 0.8)
        base = "https://autobrr.example.com"
        if widget_kind == "summary":
            return self._summary({"total_count": 18_420 + tick, "push_approved_count": 312 + tick // 30, "push_rejected_count": 41, "push_error_count": 3},
                                 [{"name": "TV 1080p", "enabled": True}, {"name": "Films 4K", "enabled": True}, {"name": "Old filter", "enabled": False}], base)
        releases = [
            {"name": "Copper.Sky.S01E04.1080p.WEB.h264-EXAMPLE", "filter": "TV 1080p", "indexer": {"name": "Tracker One"}, "size": 1_610_612_736,
             "timestamp": stamp(8 * 60), "action_status": [{"status": "PUSH_ERROR" if failed else "PUSH_APPROVED"}]},
            {"name": "Nightshift.2026.2160p.UHD.BluRay.x265-SAMPLE", "filter": "Films 4K", "indexer": {"name": "Tracker Two"}, "size": 48_318_382_080,
             "timestamp": stamp(55 * 60), "action_status": [{"status": "PUSH_REJECTED"}]},
            {"name": "Harbour.Lights.S03E05.1080p.WEB.h264-EXAMPLE", "filter": "TV 1080p", "indexer": {"name": "Tracker One"}, "size": 1_503_238_553,
             "timestamp": stamp(3 * 3600), "action_status": [{"status": "PUSH_APPROVED"}]},
            {"name": "Orbital.Decay.S01E09.720p.WEB.h264-OTHER", "filter": "", "filter_status": "FILTER_REJECTED", "indexer": {"name": "Tracker One"},
             "size": 734_003_200, "timestamp": stamp(5 * 3600), "action_status": []},
        ]
        return self._releases({"data": releases, "count": 18_420 + tick}, base)


ADAPTER = AutobrrAdapter()
