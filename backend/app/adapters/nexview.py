"""Nexview: the request dashboard of the nexapps family, one tile call."""

from __future__ import annotations

from typing import Any

from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url, human_bytes

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
        Field("api_key", "API key", type="password", secret=True, required=True, help="An administrator's key from Profile > API keys. Read-only is enough."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="requests", label="Requests", description="Waiting and running requests, with findings as the status.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=60, metrics=("waiting", "running")),
        WidgetType(kind="library", label="Library", description="Movies, series and free storage.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=300),
        WidgetType(kind="instances", label="Instances", description="Every Radarr, Sonarr and media server instance Nexview knows, and whether it answers.", renderer="list", default_size=(3, 2), refresh_seconds=60),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _tile(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> dict[str, Any]:
        return await ctx.get_json(f"{base_url(config)}/api/v1/dashboard", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        tile = await self._tile(config, ctx, cache=0)
        return f"Nexview {tile.get('version', '?')} answers."

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
        waiting = 3 + (tick // 120) % 5
        meta = {"urgent": ["Storage is running low"], "status_reason": "0 error finding(s), 1 warning(s)"}
        if widget_kind == "requests":
            return WidgetData(status="warn", primary={"label": "Waiting", "value": waiting},
                              secondary=[{"label": "Running", "value": 2}, {"label": "Tickets", "value": 1}, {"label": "Findings", "value": 1}],
                              metrics={"waiting": float(waiting), "running": 2.0}, meta=meta)
        if widget_kind == "library":
            return WidgetData(status="warn", primary={"label": "Movies", "value": 1284}, secondary=[{"label": "Series", "value": 96}, {"label": "Used", "value": "28.7 TB"}, {"label": "Free", "value": "6.2 TB"}], meta=meta)
        return WidgetData(status="warn", items=[{"title": "Radarr", "subtitle": "answers", "status": "ok"}, {"title": "Sonarr", "subtitle": "answers", "status": "ok"}, {"title": "Jellyfin", "subtitle": "1 problem(s)", "status": "warn"}, {"title": "Plex", "subtitle": "answers", "status": "ok"}], meta=meta)


ADAPTER = NexviewAdapter()
