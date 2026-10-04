"""Mailpit: the mail catcher for development, its mail counts and its newest mail.

Measured on 04.10.2026 against Mailpit 1.31.4 on docker-dev, with three
made-up mails sent over its SMTP port, once open, once behind its own login
with a webroot (issue #28).

- Mailpit has no API keys. With ``MP_UI_AUTH`` or ``--ui-auth-file`` the API
  sits behind the same Basic login as the web interface: 401 with
  ``WWW-Authenticate: Basic realm="Login"`` and the body ``Unauthorized.``,
  for no login and for a wrong one alike.
- A webroot (``MP_WEBROOT=/mail``) moves the API with it: ``/mail/api/v1``,
  and ``/api/v1`` answers 404. The URL is therefore the address of the web
  interface, webroot included.
- ``/api/v1/info`` holds the counts, the version and the newest one released,
  and the SMTP numbers since the start; ``/api/v1/webui`` says whether chaos
  is on. ``/api/v1/messages`` and ``/api/v1/search`` list mail newest first,
  with sender, subject and a snippet; a mail opens at ``/view/<ID>``.
- Reading the list does not mark anything read: only opening a mail does.
  Nothing is ever deleted or sent from here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


class MailpitAdapter(Adapter):
    kind = "mailpit"
    label = "Mailpit"
    category = "monitoring"
    description = "The mail Mailpit caught: how much, how much unread, and the newest with sender and subject."
    icon = "mailpit"
    beta = True
    docs_url = "https://mailpit.axllent.org/docs/api-v1/"
    keywords = ("Mail", "E-mail", "SMTP", "MailHog")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://mailpit:8025",
              help="The address of Mailpit's web interface. With a webroot it belongs in here, such as http://mailpit:8025/mail."),
        Field("username", "User",
              help="Only when Mailpit asks for a login (MP_UI_AUTH or --ui-auth-file); the API uses the same one."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Mailpit overview",
            description="Unread and all mail, what came in and what was refused since Mailpit started, and the size of its database.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=60,
            metrics=("unread",),
        ),
        WidgetType(
            kind="latest",
            label="Latest mail",
            description="Sender and subject of the newest mail, unread ones highlighted, each opening in Mailpit.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(
                Field("limit", "Entries", type="number", default=6, help="Between 1 and 50."),
                Field("unread_only", "Only unread mail", type="bool", default=False),
                Field("query", "Search",
                      help="Mailpit's own search, such as to:alerts@example.com or tag:backup. Empty shows all mail."),
            ),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *,
                   params: dict[str, Any] | None = None, cache: int = 30) -> Any:
        user = str(config.get("username") or "").strip()
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", params=params, cache_seconds=cache, auth_errors=False,
            auth=(user, str(config.get("password") or "")) if user else None,
            headers={"Accept": "application/json"}, verify=not config.get("insecure"),
        )
        if response.status_code == 401:
            raise AuthFailed("Mailpit asks for a login." if not user else "Mailpit rejected the user or the password.")
        if response.status_code == 404:
            raise AdapterError("There is no Mailpit API at this address.", code="http_error",
                               hint="Use the address of the web interface; with a webroot it belongs in the URL, such as http://mailpit:8025/mail.")
        if response.status_code >= 400:
            raise AdapterError(f"Mailpit answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("Mailpit did not answer with JSON; is this the address of Mailpit?", code="bad_answer") from None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/info", cache=0)
        info = info if isinstance(info, dict) else {}
        return (f"Mailpit {info.get('Version') or '?'} answers with {int(info.get('Messages') or 0)} message(s), "
                f"{int(info.get('Unread') or 0)} unread.")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "latest":
            limit = _limit(options)
            query = " ".join(part for part in (str(options.get("query") or "").strip(),
                                               "is:unread" if options.get("unread_only") else "") if part)
            if query:
                answer = await self._get(config, ctx, "/search", params={"query": query, "start": 0, "limit": limit})
            else:
                answer = await self._get(config, ctx, "/messages", params={"start": 0, "limit": limit})
            return latest_of(answer if isinstance(answer, dict) else {}, base_url(config), limit, bool(query))
        info = await self._get(config, ctx, "/info")
        webui = await self._get(config, ctx, "/webui", cache=300)
        return overview_of(info if isinstance(info, dict) else {}, webui if isinstance(webui, dict) else {})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "latest":
            now = datetime.now(UTC)
            fresh = fake.flicker("mailpit-new", tick, 0.5)
            mails = [
                ("Grafana", "alerts@example.com", "[FIRING:1] Disk almost full", 3, fresh),
                ("Backup Robot", "backup@example.com", "Nightly backup finished", 47, True),
                ("Sonarr", "sonarr@example.com", "Episode imported: Example Show S01E02", 125, False),
                ("", "cron@example.com", "Cron <root@nas> /usr/local/bin/cleanup", 260, False),
                ("Shop test", "orders@example.com", "Your order #1042 is on its way", 600, False),
            ]
            messages = [{"ID": f"demo{index}", "Read": not unread, "From": {"Name": name, "Address": address},
                         "Subject": subject, "Created": (now - timedelta(minutes=minutes)).isoformat()}
                        for index, (name, address, subject, minutes, unread) in enumerate(mails)]
            if options.get("unread_only"):
                messages = [one for one in messages if not one["Read"]]
            return latest_of({"messages": messages}, "http://mailpit.example.com", _limit(options), bool(options.get("unread_only")))
        unread = 2 if fake.flicker("mailpit-new", tick, 0.5) else 1
        return overview_of({"Version": "v1.31.4", "LatestVersion": "v1.31.4", "Messages": 214, "Unread": unread,
                            "DatabaseSize": 3_800_000,
                            "RuntimeStats": {"SMTPAccepted": int(fake.walk("mailpit-in", tick, 30, 60)), "SMTPRejected": 0}}, {})


def _limit(options: dict[str, Any]) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or 6)))
    except (TypeError, ValueError):
        return 6


def overview_of(info: dict[str, Any], webui: dict[str, Any]) -> WidgetData:
    unread = int(info.get("Unread") or 0)
    stats = info.get("RuntimeStats") if isinstance(info.get("RuntimeStats"), dict) else {}
    version = str(info.get("Version") or "")
    latest = str(info.get("LatestVersion") or "")
    reasons = []
    if webui.get("ChaosEnabled"):
        reasons.append("Chaos is on: Mailpit refuses some mail on purpose.")
    if version and latest and latest != version:
        reasons.append(f"Mailpit {latest} is out; this one is {version}.")
    return WidgetData(
        status="warn" if webui.get("ChaosEnabled") else "ok",
        primary={"label": "Unread", "value": unread},
        secondary=[
            {"label": "All mail", "value": int(info.get("Messages") or 0)},
            {"label": "Accepted", "value": int(stats.get("SMTPAccepted") or 0)},
            {"label": "Rejected", "value": int(stats.get("SMTPRejected") or 0)},
            {"label": "Database", "value": human_bytes(info.get("DatabaseSize")) if info.get("DatabaseSize") is not None else "?"},
        ],
        metrics={"unread": float(unread)},
        meta={"status_reason": " ".join(reasons)},
    )


def _sender(sender: Any) -> str:
    if not isinstance(sender, dict):
        return ""
    return str(sender.get("Name") or "").strip() or str(sender.get("Address") or "").strip()


def latest_of(answer: dict[str, Any], base: str, limit: int, searched: bool) -> WidgetData:
    items = []
    for mail in answer.get("messages") or []:
        if not isinstance(mail, dict) or not mail.get("ID"):
            continue
        unread = not mail.get("Read")
        items.append({
            "id": str(mail["ID"]),
            "title": _sender(mail.get("From")) or "?",
            "subtitle": str(mail.get("Subject") or "").strip() or "(no subject)",
            "value": ago(mail.get("Created")),
            "status": "ok" if unread else "unknown",
            "emphasis": unread,
            "url": f"{base}/view/{mail['ID']}",
        })
    return WidgetData(status="ok", items=items[:limit],
                      meta={"empty": "No mail matches the search." if searched else "No mail yet."})


ADAPTER = MailpitAdapter()
