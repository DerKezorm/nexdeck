"""Nexview: the request dashboard of the nexapps family, one tile call."""

from __future__ import annotations

from typing import Any

from .base import (
    Adapter,
    AdapterError,
    Ask,
    Choice,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
)

#: What a key has to be allowed in ``/api/v1/me`` to approve or turn down.
#:
#: ⚠️ Not the role. Nexview says so in its own documentation: an administrator
#: with a read-only key carries ``role: admin`` and still cannot approve
#: anything, so a card built on the role builds a button that always fails.
#: ``darf`` folds the account and the key together, and ``entscheiden`` is in
#: it exactly when both allow it.
MAY_DECIDE = "entscheiden"
#: Roles whose accounts may read the list of waiting requests at all, whether
#: or not their key may change anything.
DECIDING_ROLES = ("admin", "approver")

#: The sentence on a row whose request needs a target Nexview did not offer.
NO_TARGET = "Nexview handed over no target folder or profile to approve into"

#: Nexview's refusals by code, in the words this card uses. Anything else is
#: passed through as Nexview wrote it.
REFUSALS = {
    "request_not_pending": "This request is no longer waiting for approval.",
    "apikey_read_only": "This key may only read.",
    "approvers_only": "This key belongs to an account that approves nothing.",
}

#: Nexview names its findings by identifier; these are the English words for them.
FINDING_LABELS = {
    "dienst.meldet_problem": "A service reports a problem",
    "dienst.rueckkanal_gestoert": "A notification channel is failing",
    "dienst.nicht_erreichbar": "A service is unreachable",
    "dienst.version_alt": "A service runs an old version",
    "platz.knapp": "Storage is running low",
    "platz.waechst_schnell": "Storage is filling up fast",
    "nachschub.haengt": "A download is stuck",
    "nachschub.freigabe_wartet": "A request waits for approval",
    "nachschub.fehlgeschlagen": "A download failed",
    "nachschub.eingriff_noetig": "A download needs a hand",
    "bibliothek.geisterposten": "The library has ghost entries",
    "abgleich.arr_ohne_server": "An Arr instance has no media server",
    "abgleich.nicht_erkannt": "A title was not matched",
    "abgleich.jahr_widerspruch": "A release year does not match",
    "abgleich.anbieter_uneinig": "Providers disagree about a title",
    "betrieb.sicherung_fehlt": "No backup exists",
    "betrieb.sicherung_alt": "The last backup is old",
    "betrieb.mail_haengt": "Outgoing mail is stuck",
    "betrieb.protokoll_fehler": "The log shows errors",
    "betrieb.diagnose_an": "Diagnostics are switched on",
    "betrieb.aktualisierung": "An update is available",
}


class NexviewAdapter(Adapter):
    kind = "nexview"
    label = "Nexview"
    category = "media"
    description = "Open requests, findings, library size and instance health from Nexview."
    icon = "nexview"
    # Confirmed against a live Nexview 0.31 on 2026-09-05.
    beta = False
    docs_url = "https://nexview.nexapps.dev"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexview:8000"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="A key from Profile > API keys. Read-only is enough for the numbers; approving requests needs the key of an approver that may write."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="requests", label="Requests", description="Waiting and running requests, with findings as the status.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=60, metrics=("waiting", "running")),
        WidgetType(kind="library", label="Library", description="Movies, series and free storage.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=300),
        WidgetType(kind="instances", label="Instances", description="Every Radarr, Sonarr and media server instance Nexview knows, and whether it answers.", renderer="list", default_size=(3, 2), refresh_seconds=60),
        WidgetType(
            kind="approvals",
            label="Requests to approve",
            description="What waits for approval, with its cover, to approve or turn down from the board.",
            renderer="list",
            default_size=(4, 4),
            refresh_seconds=60,
            metrics=("waiting",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _tile(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> dict[str, Any]:
        return await ctx.get_json(f"{base_url(config)}/api/v1/dashboard", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        tile = await self._tile(config, ctx, cache=0)
        me = await self._me(config, ctx, cache=0)
        # ⚠️ Said at setup, not discovered on the board. A read-only key is a
        # perfectly good key for the number cards, and the approval card
        # without buttons would otherwise look like a card that forgot them.
        if MAY_DECIDE in (me.get("darf") or []):
            return f"Nexview {tile.get('version', '?')} answers. This key may approve requests."
        return (f"Nexview {tile.get('version', '?')} answers. This key may not approve, "
                "so the approval card shows requests without buttons.")

    async def _me(self, config: dict[str, Any], ctx: Context, cache: float = 300) -> dict[str, Any]:
        """Who this key is and what it may do, from Nexview's own answer."""
        answer = await ctx.get_json(f"{base_url(config)}/api/v1/me", headers=self._headers(config),
                                    verify=not config.get("insecure"), cache_seconds=cache)
        return answer if isinstance(answer, dict) else {}

    async def _targets(self, config: dict[str, Any], ctx: Context, media_type: str, tier: str) -> dict[str, Any] | None:
        """The folders and profiles a request of this kind may be approved into.

        ⚠️ Per media type **and** tier. A film and a series go to different
        instances, and so do the same film in 1080p and in 4K; one list for
        all of them would be wrong for three of the four. Nothing when Nexview
        cannot say, which the caller turns into "no button" rather than into
        an empty list that looks like a choice.
        """
        if media_type not in ("movie", "tv") or tier not in ("standard", "uhd"):
            return None
        try:
            answer = await ctx.get_json(f"{base_url(config)}/api/arr/{media_type}/options", params={"tier": tier},
                                        headers=self._headers(config), verify=not config.get("insecure"),
                                        cache_seconds=300)
        except AdapterError:
            return None
        return answer if isinstance(answer, dict) else None

    async def _approvals(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        me = await self._me(config, ctx)
        role = str((me.get("konto") or {}).get("role") or "")
        if role not in DECIDING_ROLES:
            return WidgetData(status="unknown", meta={
                "notice": "This key belongs to an account that approves nothing, so there is nothing to list.",
                "empty": "Nothing to show",
            })
        may_decide = MAY_DECIDE in (me.get("darf") or [])

        response = await ctx.request("GET", f"{base_url(config)}/api/admin/requests",
                                     params={"status": "pending_approval"}, headers=self._headers(config),
                                     verify=not config.get("insecure"), cache_seconds=30, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(self._refusal(response), code="http_error")
        try:
            rows = response.json()
        except ValueError as error:
            raise AdapterError("Nexview did not answer with its list of requests.", code="not_json") from error
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        shown = rows[: max(1, int(options.get("limit") or 8))]

        # One question per instance, not per row: ten films waiting are one
        # list of folders, not ten.
        wanted = {(str(row.get("media_type")), str(row.get("tier") or "standard")) for row in shown
                  if row.get("root_folder_path") is None or row.get("quality_profile_id") is None}
        targets = {kind: await self._targets(config, ctx, *kind) for kind in sorted(wanted)} if may_decide else {}

        items = [self._approval_row(row, targets, may_decide) for row in shown]
        items = [item for item in items if item is not None]
        # The rows exist to be pressed, so their buttons show without a
        # hover: a wall display with a touchscreen has none.
        meta: dict[str, Any] = {"empty": "Nothing is waiting for approval.", "actions_visible": True}
        if not may_decide:
            meta["notice"] = "This key may only read. Approving needs an approver's key that may write."
        return WidgetData(
            status="warn" if rows else "ok",
            items=items,
            secondary=[{"label": "Waiting", "value": len(rows)}],
            metrics={"waiting": float(len(rows))},
            meta=meta,
        )

    @staticmethod
    def _approval_row(row: dict[str, Any], targets: dict[tuple[str, str], dict[str, Any] | None],
                      may_decide: bool) -> dict[str, Any] | None:
        request_id = row.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 1:
            return None
        title = str(row.get("title") or "?")
        if row.get("season"):
            title = f"{title} · S{row['season']}"
        item: dict[str, Any] = {
            "id": request_id,
            "title": title,
            "subtitle": str(row.get("display_name") or row.get("username") or ""),
            "value": "4K" if row.get("tier") == "uhd" else "",
            # A whole address already: Nexview builds it from TMDB's image base.
            "art": str(row.get("poster_path") or ""),
            "status": "warn",
        }
        if not may_decide:
            return item

        needs_folder = row.get("root_folder_path") is None
        needs_profile = row.get("quality_profile_id") is None
        approve: dict[str, Any] | None = {"id": "approve", "label": "Approve", "icon": "check", "params": {"id": request_id}}
        if needs_folder or needs_profile:
            offer = targets.get((str(row.get("media_type")), str(row.get("tier") or "standard"))) or {}
            folders = [Choice(value=str(one["path"]), label=str(one["path"]))
                       for one in offer.get("root_folders") or [] if isinstance(one, dict) and one.get("path")]
            profiles = [Choice(value=str(one["id"]), label=str(one.get("name") or one["id"]))
                        for one in offer.get("quality_profiles") or [] if isinstance(one, dict) and one.get("id") is not None]
            if (needs_folder and not folders) or (needs_profile and not profiles):
                # ⚠️ No button rather than a button with an empty list. An
                # empty choice looks like a question with no answer, and
                # pressing it would only earn Nexview's refusal.
                approve = None
                item["subtitle"] = NO_TARGET
            else:
                asks = []
                if needs_folder:
                    asks.append(Ask(name="root_folder_path", label="Target folder", kind="choice", options=folders).model_dump())
                if needs_profile:
                    asks.append(Ask(name="quality_profile_id", label="Quality profile", kind="choice", options=profiles).model_dump())
                approve["asks"] = asks
        item["actions"] = ([approve] if approve else []) + [
            {"id": "reject", "label": "Turn down", "icon": "x", "danger": True, "confirm": True, "params": {"id": request_id}},
        ]
        return item

    @staticmethod
    def _refusal(response: Any) -> str:
        """Nexview's own reason, which is the one that says what to do.

        Nexview answers ``{"detail": {"code", "message"}}``; the message is its
        German fallback, so a known code is put in this card's words and
        anything else is passed through rather than replaced by a status code.
        """
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, dict):
            code = str(detail.get("code") or "")
            if code in REFUSALS:
                return REFUSALS[code]
            if detail.get("message"):
                return str(detail["message"])[:200]
        if isinstance(detail, str) and detail:
            return detail[:200]
        return f"Nexview refused with HTTP {response.status_code}."

    @staticmethod
    def _status(findings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """The card's status follows the findings: one error turns it red, a warning yellow.

        The reason travels along, so the dot can say why it is red instead of
        looking like Nexview itself were broken.
        """
        errors = int(findings.get("fehler") or 0)
        warnings = int(findings.get("warnung") or 0)
        status = "bad" if errors else ("warn" if warnings else "ok")
        urgent = [FINDING_LABELS.get(k, k.replace(".", " ").replace("_", " ")) for k in findings.get("dringendste") or []]
        meta: dict[str, Any] = {"urgent": urgent}
        if errors or warnings:
            meta["status_reason"] = f"{errors} error finding(s), {warnings} warning(s)"
        return status, meta

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "approvals":
            return await self._approvals(config, options, ctx)
        tile = await self._tile(config, ctx)
        findings = tile.get("befunde") or {}
        status, meta = self._status(findings)
        if widget_kind == "requests":
            requests = tile.get("anfragen") or {}
            return WidgetData(
                status=status,
                primary={"label": "Waiting", "value": int(requests.get("wartend") or 0)},
                secondary=[{"label": "Running", "value": int(requests.get("laufend") or 0)}, {"label": "Tickets", "value": int(tile.get("tickets_offen") or 0)}, {"label": "Findings", "value": int(findings.get("fehler") or 0) + int(findings.get("warnung") or 0)}],
                metrics={"waiting": float(requests.get("wartend") or 0), "running": float(requests.get("laufend") or 0)},
                meta=meta,
            )
        if widget_kind == "library":
            library = tile.get("bibliothek") or {}
            return WidgetData(
                status=status,
                primary={"label": "Movies", "value": int(library.get("filme") or 0)},
                secondary=[{"label": "Series", "value": int(library.get("serien") or 0)}, {"label": "Used", "value": human_bytes(library.get("belegt_bytes"))}, {"label": "Free", "value": human_bytes(library.get("frei_bytes"))}],
                meta=meta,
            )
        items = [{"title": i.get("name", "?"), "subtitle": f"{i.get('probleme', 0)} problem(s)" if i.get("probleme") else "answers", "status": "ok" if i.get("erreichbar") and not i.get("probleme") else ("warn" if i.get("erreichbar") else "bad")} for i in tile.get("instanzen") or []]
        return WidgetData(status=status, items=items, meta=meta)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "approvals":
            demo_targets = {("movie", "uhd"): {
                "root_folders": [{"path": "/media/films-4k"}, {"path": "/media/kids-4k"}],
                "quality_profiles": [{"id": 7, "name": "Ultra-HD"}],
            }}
            rows = [
                {"id": 101, "title": "The Quiet Harbour", "display_name": "Anna", "media_type": "movie", "tier": "standard",
                 "root_folder_path": "/media/films", "quality_profile_id": 4},
                {"id": 102, "title": "Copper Sky", "display_name": "Ben", "media_type": "movie", "tier": "uhd",
                 "root_folder_path": None, "quality_profile_id": None},
                {"id": 103, "title": "Harbour Lights", "season": 3, "display_name": "Anna", "media_type": "tv",
                 "tier": "standard", "root_folder_path": "/media/series", "quality_profile_id": 4},
            ]
            waiting = len(rows) + (tick // 300) % 2
            return WidgetData(
                status="warn",
                items=[self._approval_row(row, demo_targets, True) for row in rows][: int(options.get("limit") or 8)],
                secondary=[{"label": "Waiting", "value": waiting}],
                metrics={"waiting": float(waiting)},
                meta={"empty": "Nothing is waiting for approval.", "actions_visible": True},
            )
        waiting = 3 + (tick // 120) % 5
        meta = {"urgent": ["Storage is running low"], "status_reason": "0 error finding(s), 1 warning(s)"}
        if widget_kind == "requests":
            return WidgetData(status="warn", primary={"label": "Waiting", "value": waiting},
                              secondary=[{"label": "Running", "value": 2}, {"label": "Tickets", "value": 1}, {"label": "Findings", "value": 1}],
                              metrics={"waiting": float(waiting), "running": 2.0}, meta=meta)
        if widget_kind == "library":
            return WidgetData(status="warn", primary={"label": "Movies", "value": 1284}, secondary=[{"label": "Series", "value": 96}, {"label": "Used", "value": "28.7 TB"}, {"label": "Free", "value": "6.2 TB"}], meta=meta)
        return WidgetData(status="warn", items=[{"title": "Radarr", "subtitle": "answers", "status": "ok"}, {"title": "Sonarr", "subtitle": "answers", "status": "ok"}, {"title": "Jellyfin", "subtitle": "1 problem(s)", "status": "warn"}, {"title": "Plex", "subtitle": "answers", "status": "ok"}], meta=meta)


    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "approvals" or action_id not in ("approve", "reject"):
            raise AdapterError("This widget has no such action.", code="no_such_action")
        request_id = params.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 1:
            raise AdapterError("That is not a request Nexview could know.", code="bad_param")

        body: dict[str, Any] = {}
        if action_id == "approve":
            if params.get("root_folder_path"):
                body["root_folder_path"] = str(params["root_folder_path"])
            if params.get("quality_profile_id") not in (None, ""):
                try:
                    body["quality_profile_id"] = int(params["quality_profile_id"])
                except (TypeError, ValueError) as error:
                    raise AdapterError("That is not a quality profile.", code="bad_param") from error

        response = await ctx.request(
            "POST", f"{base_url(config)}/api/admin/requests/{request_id}/{action_id}",
            json_body=body, headers=self._headers(config), verify=not config.get("insecure"),
            # ⚠️ Not turned into "the credentials were rejected". Nexview
            # answers 403 for a read-only key and for an account that may not
            # decide, and both say precisely that in their own words.
            auth_errors=False,
        )
        if response.status_code >= 400:
            raise AdapterError(self._refusal(response), code="rejected")
        return "Approved." if action_id == "approve" else "Turned down."


ADAPTER = NexviewAdapter()
