"""Alertmanager: the alerts that fire, how many are silenced, and the silences.

Read through API v2, the one Alertmanager has served since 0.16 and the only
one since 0.27. Measured against Alertmanager 0.34.1 with invented alerts and
silences:

- ``GET /api/v2/alerts`` hands out every alert it holds, silenced and
  inhibited ones included, each with ``status.state`` of ``active`` or
  ``suppressed`` and the reason in ``silencedBy``, ``inhibitedBy`` and
  ``mutedBy`` (a time interval of the route). One request serves all cards;
  the split is made here.
- ``GET /api/v2/silences`` keeps expired silences for days (the retention,
  five by default), so the list is filtered by ``status.state``. A silence
  that starts later is ``pending``.
- ``severity`` is a label like any other. Nothing in Alertmanager sets it or
  says what its values are; an alert without it is shown, uncoloured.

Alertmanager has no sign-in of its own. A proxy in front of it may want basic
authentication or a bearer token, and Grafana's and Mimir's built-in
Alertmanagers serve the same API under a path of their own, which goes into
the URL.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
)

#: Severity labels that mean "wake somebody", and those that mean "look at it today".
#: Lower case; whoever writes the rules picks the words.
CRITICAL = {"critical", "page", "error", "emergency", "alert", "fatal", "disaster", "high"}
WARNING = {"warning", "warn", "major", "minor", "average", "medium"}

#: Where a row of each kind stands in a list, worst first.
RANK = {"bad": 0, "warn": 1, "unknown": 2}


def _severity(alert: dict[str, Any]) -> str:
    """The colour of an alert from its severity label: bad, warn, or unknown for anything else."""
    word = str((alert.get("labels") or {}).get("severity") or "").strip().lower()
    return "bad" if word in CRITICAL else "warn" if word in WARNING else "unknown"


def _seconds(moment: Any) -> float | None:
    try:
        when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def _ahead(moment: Any, now: float) -> str:
    """How long until a moment: "in 40 min", "in 5 h", "in 2 d"."""
    at = _seconds(moment)
    if at is None:
        return ""
    seconds = max(0.0, at - now)
    if seconds < 3600:
        return f"in {max(1, round(seconds / 60))} min"
    if seconds < 86400:
        return f"in {round(seconds / 3600)} h"
    return f"in {round(seconds / 86400)} d"


def _matchers(silence: dict[str, Any]) -> str:
    """A silence's matchers as Alertmanager writes them: name="value", =~ for a pattern, ! for not."""
    parts = []
    for one in silence.get("matchers") or []:
        if not isinstance(one, dict):
            continue
        sign = ("=~" if one.get("isRegex") else "=") if one.get("isEqual", True) else ("!~" if one.get("isRegex") else "!=")
        parts.append(f'{one.get("name")}{sign}"{one.get("value")}"')
    return ", ".join(parts) or "?"


def _http(url: Any) -> str:
    """A link of the alert's own, only when it is a web address."""
    text = str(url or "")
    return text if text.startswith(("http://", "https://")) else ""


class AlertmanagerAdapter(Adapter):
    kind = "alertmanager"
    label = "Alertmanager"
    category = "monitoring"
    description = "The alerts that fire, critical first, and the silences that keep the others quiet."
    icon = "alertmanager"
    docs_url = "https://prometheus.io/docs/alerting/latest/alertmanager/"
    keywords = ("Prometheus", "alerts", "silences")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://alertmanager:9093",
              help="With the path, when Alertmanager sits under one, as in Grafana or Mimir."),
        Field("username", "User name", help="Only behind basic authentication."),
        Field("password", "Password", type="password", secret=True),
        Field("token", "Bearer token", type="password", secret=True, help="Only when a proxy in front of Alertmanager wants one."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="alerts",
            label="Firing alerts",
            description="Every alert that fires and nobody silenced, critical first, with what it is about and since when.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=30,
            metrics=("firing", "critical"),
            options=(
                Field("filter", "Matchers", type="textarea", placeholder='severity="critical"',
                      help='One per line, as in Alertmanager: name="value", name=~"pattern", name!="value". Only alerts matching all of them are shown.'),
                Field("suppressed", "Show silenced and inhibited alerts", type="bool", default=False),
                Field("limit", "Entries", type="number", default=10),
            ),
        ),
        WidgetType(
            kind="summary",
            label="Alertmanager",
            description="How many alerts fire, how many of them are critical, and how many are kept quiet by a silence or an inhibition.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("firing", "critical"),
        ),
        WidgetType(
            kind="silences",
            label="Silences",
            description="The silences in force and the ones that start later, with their matchers, who set them and when they end.",
            renderer="list",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        headers = {"Authorization": f"Bearer {config['token']}"} if config.get("token") else None
        auth = (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None
        response = await ctx.request("GET", f"{base_url(config)}/api/v2{path}", headers=headers, params=params, auth=auth,
                                     verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        if response.status_code in (401, 403):
            failure = AuthFailed("Alertmanager, or the proxy in front of it, refused the request.")
            failure.hint = "Alertmanager has no sign-in of its own; the user, password or token are those of the proxy."
            raise failure
        if response.status_code == 400 and path == "/alerts":
            raise AdapterError("Alertmanager did not accept the matchers of this card.", code="bad_filter",
                               hint='Write one per line, as name="value" or name=~"pattern".')
        if response.status_code == 404:
            raise AdapterError("This address has no Alertmanager API v2.", code="not_alertmanager",
                               hint="Point the URL at Alertmanager itself, usually port 9093, with the path in front of /api/v2 when there is one.")
        if response.status_code >= 400:
            raise AdapterError(f"Alertmanager answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Alertmanager did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _alerts(self, config: dict[str, Any], ctx: Context, matchers: list[str] | None = None) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/alerts", {"filter": matchers} if matchers else None)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Alertmanager does.", code="not_alertmanager")
        return [one for one in answer if isinstance(one, dict)]

    async def _silences(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/silences", cache=30)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Alertmanager does.", code="not_alertmanager")
        return [one for one in answer if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status", cache=0)
        if not isinstance(status, dict) or "versionInfo" not in status:
            raise AdapterError("This address answers, but not the way Alertmanager does.", code="not_alertmanager")
        version = (status.get("versionInfo") or {}).get("version") or "?"
        peers = len((status.get("cluster") or {}).get("peers") or [])
        firing = sum(1 for one in await self._alerts(config, ctx) if (one.get("status") or {}).get("state") == "active")
        cluster = f", in a cluster of {peers}" if peers > 1 else ""
        return f"Alertmanager {version} answers{cluster}: {firing} alerts firing."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        now = time.time()
        if widget_kind == "silences":
            silences = await self._silences(config, ctx)
            return self.silence_list(silences, await self._alerts(config, ctx), options, now)
        if widget_kind == "summary":
            return self.summary(await self._alerts(config, ctx), await self._silences(config, ctx))
        matchers = [line.strip() for line in str(options.get("filter") or "").splitlines() if line.strip()]
        return self.alert_list(await self._alerts(config, ctx, matchers), options, now)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def alert_list(alerts: list[dict[str, Any]], options: dict[str, Any], now: float) -> WidgetData:
        show_quiet = bool(options.get("suppressed"))
        firing = [one for one in alerts if (one.get("status") or {}).get("state") == "active"]
        quiet = [one for one in alerts if (one.get("status") or {}).get("state") == "suppressed"]
        shown = firing + (quiet if show_quiet else [])
        shown.sort(key=lambda one: -(_seconds(one.get("startsAt")) or 0))
        shown.sort(key=lambda one: (one in quiet, RANK[_severity(one)]))
        items = []
        for one in shown[: max(1, int(options.get("limit") or 10))]:
            labels, notes, state = one.get("labels") or {}, one.get("annotations") or {}, one.get("status") or {}
            why = "Silenced" if state.get("silencedBy") else "Inhibited" if state.get("inhibitedBy") else "Muted" if state.get("mutedBy") else ""
            pieces = (why, str(labels.get("severity") or ""), str(labels.get("instance") or labels.get("job") or ""),
                      str(notes.get("summary") or notes.get("description") or ""))
            items.append({
                "title": str(labels.get("alertname") or "?"),
                "subtitle": " · ".join(piece for piece in pieces if piece),
                "status": "unknown" if why else _severity(one),
                "value": ago(one.get("startsAt"), now=now),
                "url": _http(one.get("generatorURL")),
            })
        critical = sum(1 for one in firing if _severity(one) == "bad")
        return WidgetData(
            status="bad" if critical else "warn" if any(_severity(one) == "warn" for one in firing) else "ok",
            items=items,
            secondary=[{"label": "Firing", "value": len(firing)}, {"label": "Critical", "value": critical},
                       {"label": "Silenced", "value": len(quiet)}],
            meta={"empty": "No alert is firing."},
            metrics={"firing": float(len(firing)), "critical": float(critical)},
        )

    @staticmethod
    def summary(alerts: list[dict[str, Any]], silences: list[dict[str, Any]]) -> WidgetData:
        firing = [one for one in alerts if (one.get("status") or {}).get("state") == "active"]
        critical = sum(1 for one in firing if _severity(one) == "bad")
        warning = sum(1 for one in firing if _severity(one) == "warn")
        silenced = sum(1 for one in alerts if (one.get("status") or {}).get("silencedBy"))
        inhibited = sum(1 for one in alerts if (one.get("status") or {}).get("inhibitedBy") and not (one.get("status") or {}).get("silencedBy"))
        in_force = sum(1 for one in silences if (one.get("status") or {}).get("state") == "active")
        return WidgetData(
            status="bad" if critical else "warn" if warning else "ok",
            primary={"label": "Firing", "value": len(firing)},
            secondary=[
                {"label": "Critical", "value": critical},
                {"label": "Warning", "value": warning},
                {"label": "Silenced", "value": silenced},
                {"label": "Inhibited", "value": inhibited},
                {"label": "Silences", "value": in_force},
            ],
            metrics={"firing": float(len(firing)), "critical": float(critical)},
        )

    @staticmethod
    def silence_list(silences: list[dict[str, Any]], alerts: list[dict[str, Any]], options: dict[str, Any], now: float) -> WidgetData:
        muted: dict[str, int] = {}
        for alert in alerts:
            for silence_id in (alert.get("status") or {}).get("silencedBy") or []:
                muted[silence_id] = muted.get(silence_id, 0) + 1
        live = [one for one in silences if (one.get("status") or {}).get("state") in ("active", "pending")]
        # In force first, the one that ends soonest at the top; then those still to come, the nearest first.
        live.sort(key=lambda one: ((one.get("status") or {}).get("state") != "active",
                                   _seconds(one.get("endsAt") if (one.get("status") or {}).get("state") == "active" else one.get("startsAt")) or 0))
        items = []
        for one in live[: max(1, int(options.get("limit") or 10))]:
            pending = (one.get("status") or {}).get("state") == "pending"
            count = muted.get(str(one.get("id")), 0)
            # A silence still to come says when it starts, one in force when it ends.
            pieces = ("Pending" if pending else f"{count} alert(s)" if count else "",
                      str(one.get("comment") or ""), str(one.get("createdBy") or ""))
            items.append({
                "title": _matchers(one),
                "subtitle": " · ".join(piece for piece in pieces if piece),
                "status": "unknown" if pending else "ok",
                "value": _ahead(one.get("startsAt") if pending else one.get("endsAt"), now),
            })
        active = sum(1 for one in live if (one.get("status") or {}).get("state") == "active")
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Silences", "value": active}, {"label": "Pending", "value": len(live) - active}],
            meta={"empty": "No silence is in force."},
        )

    # -- demo ----------------------------------------------------------------

    @staticmethod
    def demo_alerts(tick: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
        now = time.time()
        stamp = lambda seconds: datetime.fromtimestamp(now + seconds, UTC).isoformat().replace("+00:00", "Z")  # noqa: E731
        down = (tick // 120) % 4 != 3
        alerts = [
            {"labels": {"alertname": "DiskFilling", "severity": "warning", "instance": "nas.example.com"},
             "annotations": {"summary": f"Volume {int(fake.walk('am-disk', tick, 86, 94))} percent full"},
             "startsAt": stamp(-5400), "status": {"state": "active", "silencedBy": [], "inhibitedBy": []}},
            {"labels": {"alertname": "BackupLate", "severity": "info", "instance": "backup.example.com"},
             "annotations": {"description": "Last backup 30 hours ago"},
             "startsAt": stamp(-7200), "status": {"state": "suppressed", "silencedBy": ["s1"], "inhibitedBy": []}},
        ]
        if down:
            alerts.insert(0, {"labels": {"alertname": "HostDown", "severity": "critical", "instance": "node2.example.com"},
                              "annotations": {"summary": "node2 does not answer"},
                              "startsAt": stamp(-900), "status": {"state": "active", "silencedBy": [], "inhibitedBy": []}})
            alerts.append({"labels": {"alertname": "ServiceSlow", "severity": "warning", "instance": "node2.example.com"},
                           "startsAt": stamp(-600), "status": {"state": "suppressed", "silencedBy": [], "inhibitedBy": ["x"]}})
        silences = [
            {"id": "s1", "status": {"state": "active"}, "comment": "Backup host in maintenance", "createdBy": "operator",
             "startsAt": stamp(-3600), "endsAt": stamp(4 * 3600),
             "matchers": [{"name": "alertname", "value": "BackupLate", "isRegex": False, "isEqual": True}]},
            {"id": "s2", "status": {"state": "pending"}, "comment": "Planned reboot", "createdBy": "operator",
             "startsAt": stamp(86400), "endsAt": stamp(90000),
             "matchers": [{"name": "instance", "value": "node[0-9]+.*", "isRegex": True, "isEqual": True}]},
        ]
        return alerts, silences, now

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        alerts, silences, now = self.demo_alerts(tick)
        if widget_kind == "summary":
            return self.summary(alerts, silences)
        if widget_kind == "silences":
            return self.silence_list(silences, alerts, options, now)
        return self.alert_list(alerts, options, now)


ADAPTER = AlertmanagerAdapter()
