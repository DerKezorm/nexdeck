"""mailcow: domains, mailboxes, the Postfix queue and the state of its containers.

mailcow's API (``/api/v1``) takes the key in the header ``X-API-Key``. It is
made in the admin interface under System > Access > Edit administrator >
API, with the allowed addresses listed there: a call from an address that is
not on the list is refused even with the right key. The read-only key is
enough for every card; the one button needs the read/write key.

Not measured. mailcow runs more than twenty containers and was not started
for this adapter; everything here follows mailcow's own OpenAPI file
(``data/web/api/openapi.yaml``, October 2026) and Postfix's ``postqueue -j``,
whose lines mailcow hands out as they are. Two places are guesses worth a
look when it meets a real server:

* The queue's recipients are strings in the OpenAPI example and objects with
  ``address`` and ``delay_reason`` in ``postqueue -j``. Both are read.
* Numbers such as ``bytes_total`` and ``msgs_total`` arrive as strings.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Action,
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
    percent,
    status_from_percent,
)

#: A queue longer than this is yellow even when nothing says why.
LONG_QUEUE = 50


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _switched_on(value: Any) -> bool:
    """mailcow writes booleans as 1, "1", true or True depending on the table."""
    return str(value).lower() in ("1", "true")


def recipients_of(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Each recipient of a queued message with the reason it is delayed ('' if none)."""
    found = []
    for one in entry.get("recipients") or []:
        if isinstance(one, dict):
            found.append((str(one.get("address") or "?"), " ".join(str(one.get("delay_reason") or "").split())[:160]))
        else:
            found.append((str(one), ""))
    return found


class MailcowAdapter(Adapter):
    kind = "mailcow"
    label = "mailcow"
    category = "other"
    description = "Domains, mailboxes, the mail queue with the reasons for delays, and the state of the containers of a mailcow server."
    icon = "mailcow"
    docs_url = "https://docs.mailcow.email/third_party/api/"
    #: Built from the documentation and not run against a mailcow; it stays beta until somebody confirms it on a server.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://mail.example.com",
              help="The address of the mailcow web interface."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="From System > Access > Edit administrator > API. The read-only key fills every card; flushing the queue needs the read/write key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In mailcow's admin interface open System > Access, edit the administrator and open API.",
        "Switch the API on, add the address nexdeck connects from to the allowed addresses, and copy the read-only key.",
        "A call from an address that is not on the list is refused, whatever key it carries.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="Mailboxes, domains, the length of the queue, containers that are not running and how full the mail disk is.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("queue", "containers_down"),
        ),
        WidgetType(
            kind="queue",
            label="Mail queue",
            description="Messages Postfix keeps for later, the delayed ones first, with the reason it gave.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="containers",
            label="Containers",
            description="Every mailcow container with its state, the ones that are not running first.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
        ),
        WidgetType(
            kind="mailboxes",
            bars=True,
            label="Mailboxes",
            description="Every mailbox with the space it uses, the fullest first, red near the quota.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="domains",
            bars=True,
            label="Domains",
            description="Every domain with its mailboxes against the limit, and the space they use.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=900,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 20) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/get/{path}",
            headers={"X-API-Key": str(config.get("api_key") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=cache,
        )
        if response.status_code >= 400:
            raise AdapterError(f"mailcow answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the web interface.")
        try:
            body = response.json()
        except ValueError as error:
            raise AdapterError("mailcow did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service, or at a proxy that answers with a page.") from error
        # ⚠️ A key that is wrong, or a call from an address that is not on the allowed list, is
        # an ordinary 200 with {"type": "error", "msg": "authentication failed"} (from mailcow's
        # code, not measured).
        if isinstance(body, dict) and body.get("type") == "error":
            raise AuthFailed(f"mailcow refused the call: {str(body.get('msg') or 'authentication failed')[:120]}")
        return body

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "status/version", cache=0)
        return f"mailcow {(version or {}).get('version', '?')} answers."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        # mailcow numbers its releases by month (2026-10), which no upstream list can compare.
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "queue":
            return self._queue(await self._get(config, ctx, "mailq/all", cache=15), options)
        if widget_kind == "containers":
            return self._containers(await self._get(config, ctx, "status/containers"))
        if widget_kind == "mailboxes":
            return self._mailboxes(await self._get(config, ctx, "mailbox/all", cache=120), options)
        if widget_kind == "domains":
            return self._domains(await self._get(config, ctx, "domain/all", cache=120))
        queue = await self._get(config, ctx, "mailq/all", cache=15)
        containers = await self._get(config, ctx, "status/containers")
        mailboxes = await self._get(config, ctx, "mailbox/all", cache=120)
        domains = await self._get(config, ctx, "domain/all", cache=120)
        try:
            vmail = await self._get(config, ctx, "status/vmail", cache=120)
        except AdapterError:
            vmail = None
        return self._overview(queue, containers, mailboxes, domains, vmail)

    def _overview(self, queue: Any, containers: Any, mailboxes: Any, domains: Any, vmail: Any) -> WidgetData:
        entries = [one for one in queue if isinstance(one, dict)] if isinstance(queue, list) else []
        delayed = sum(1 for one in entries if any(reason for _address, reason in recipients_of(one)))
        down = [name for name, one in (containers or {}).items() if isinstance(one, dict) and one.get("state") != "running"] \
            if isinstance(containers, dict) else []
        used = None
        if isinstance(vmail, dict):
            used = _number(str(vmail.get("used_percent") or "").rstrip("%")) if vmail.get("used_percent") else None
        secondary = [
            {"label": "Mailboxes", "value": len(mailboxes) if isinstance(mailboxes, list) else 0},
            {"label": "Domains", "value": len(domains) if isinstance(domains, list) else 0},
            {"label": "Containers down", "value": len(down)},
        ]
        if used is not None:
            secondary.append({"label": "Mail disk", "value": used, "unit": "%"})
        status = "bad" if down else "warn" if delayed or len(entries) > LONG_QUEUE else "ok"
        if used is not None:
            order = ("ok", "warn", "bad")
            status = max(status, status_from_percent(used), key=order.index)
        return WidgetData(
            status=status,
            primary={"label": "Queued", "value": len(entries)},
            secondary=secondary,
            metrics={"queue": float(len(entries)), "containers_down": float(len(down))},
        )

    def _queue(self, queue: Any, options: dict[str, Any], now: float | None = None) -> WidgetData:
        now = now if now is not None else time.time()
        entries = [one for one in queue if isinstance(one, dict)] if isinstance(queue, list) else []
        rows = []
        for entry in entries:
            recipients = recipients_of(entry)
            reason = next((why for _address, why in recipients if why), "")
            first = recipients[0][0] if recipients else "?"
            more = len(recipients) - 1
            parts = [
                reason,
                str(entry.get("queue_name") or ""),
                human_bytes(entry.get("message_size")) if entry.get("message_size") else "",
                f"{ago(entry.get('arrival_time'), now)} old" if entry.get("arrival_time") else "",
            ]
            rows.append((0 if reason else 1, {
                "title": f"{entry.get('sender') or '?'} → {first}" + (f" +{more}" if more > 0 else ""),
                "subtitle": " · ".join(part for part in parts if part),
                "status": "warn" if reason else "ok",
                "value": "Delayed" if reason else "Waiting",
            }))
        rows.sort(key=lambda row: row[0])
        items = [item for _rank, item in rows][: int(options.get("limit") or 10)]
        return WidgetData(
            status="warn" if any(item["status"] == "warn" for item in items) or len(entries) > LONG_QUEUE else "ok",
            items=items,
            secondary=[{"label": "Queued", "value": len(entries)}],
            actions=[Action(id="flush", label="Flush queue", icon="refresh-cw", confirm=True)] if entries else [],
        )

    def _containers(self, containers: Any) -> WidgetData:
        rows = []
        for name, one in (containers.items() if isinstance(containers, dict) else []):
            if not isinstance(one, dict):
                continue
            running = one.get("state") == "running"
            started = ago(one.get("started_at"))
            rows.append({
                "title": str(one.get("container") or name),
                "subtitle": " · ".join(part for part in (str(one.get("image") or ""), f"up {started}" if running and started else "") if part),
                "status": "ok" if running else "bad",
                "value": "Running" if running else str(one.get("state") or "Unknown").capitalize(),
            })
        rows.sort(key=lambda row: (row["status"] == "ok", row["title"]))
        down = sum(1 for row in rows if row["status"] == "bad")
        return WidgetData(
            status="bad" if down else "ok",
            items=rows,
            secondary=[{"label": "Containers", "value": len(rows)}, {"label": "Containers down", "value": down}],
        )

    def _mailboxes(self, mailboxes: Any, options: dict[str, Any]) -> WidgetData:
        rows = []
        for one in mailboxes if isinstance(mailboxes, list) else []:
            if not isinstance(one, dict):
                continue
            used = int(_number(one.get("quota_used")))
            quota = int(_number(one.get("quota")))
            share = percent(used, quota) if quota > 0 else None
            active = _switched_on(one.get("active"))
            rows.append({
                "title": str(one.get("username") or "?"),
                "subtitle": " · ".join(part for part in (
                    f"{human_bytes(used)} of {human_bytes(quota)}" if quota > 0 else human_bytes(used),
                    "" if active else "Switched off") if part),
                "status": status_from_percent(share) if share is not None else "ok",
                "value": used,
            })
        rows.sort(key=lambda row: (-row["value"], row["title"]))
        states = {row["status"] for row in rows}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Mailboxes", "value": len(rows)}],
        )

    def _domains(self, domains: Any) -> WidgetData:
        rows = []
        for one in domains if isinstance(domains, list) else []:
            if not isinstance(one, dict):
                continue
            boxes = int(_number(one.get("mboxes_in_domain")))
            limit = int(_number(one.get("max_num_mboxes_for_domain")))
            active = _switched_on(one.get("active"))
            used = int(_number(one.get("quota_used_in_domain")))
            rows.append({
                "title": str(one.get("domain_name") or "?"),
                "subtitle": " · ".join(part for part in (
                    f"{boxes} of {limit} mailboxes" if limit else f"{boxes} mailboxes",
                    human_bytes(used) if used else "",
                    "Switched off" if not active else "", "Backup MX" if _switched_on(one.get("backupmx")) else "") if part),
                "status": "ok" if active else "warn",
                "value": boxes,
            })
        rows.sort(key=lambda row: (row["status"] == "ok", row["title"]))
        return WidgetData(
            status="warn" if any(row["status"] == "warn" for row in rows) else "ok",
            items=rows,
            secondary=[{"label": "Domains", "value": len(rows)}],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "flush":
            raise AdapterError("mailcow has no such action.", code="no_such_action")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/edit/mailq",
            headers={"X-API-Key": str(config.get("api_key") or ""), "Accept": "application/json"},
            json_body={"action": "flush"}, verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AdapterError(f"mailcow answered with HTTP {response.status_code}.", code="http_error")
        try:
            body = response.json()
        except ValueError:
            body = None
        reply = body[0] if isinstance(body, list) and body else body
        if isinstance(reply, dict) and reply.get("type") in ("error", "danger"):
            raise AdapterError(f"mailcow did not flush the queue: {str(reply.get('msg') or '')[:160]}", code="not_flushed",
                               hint="Flushing needs the read/write API key, not the read-only one.")
        ctx.forget_answers()
        return "The queue is being flushed."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        delayed = fake.flicker("mailcow-delay", tick, 0.5)
        queue = [
            {"queue_id": "B98C6260CA1", "queue_name": "deferred", "arrival_time": int(now - 5400), "message_size": 48_000,
             "sender": "alice@example.com",
             "recipients": [{"address": "carol@example.net", "delay_reason": "connect to mail.example.net[192.0.2.9]:25: Connection timed out"}]},
            {"queue_id": "C21D4670CB2", "queue_name": "active", "arrival_time": int(now - 40), "message_size": 9_000,
             "sender": "bob@example.com", "recipients": [{"address": "dave@example.org", "delay_reason": ""}]},
        ]
        if not delayed:
            queue = queue[1:]
        names = ["postfix-mailcow", "dovecot-mailcow", "rspamd-mailcow", "sogo-mailcow", "nginx-mailcow", "redis-mailcow", "mysql-mailcow", "clamd-mailcow"]
        down = fake.flicker("mailcow-down", tick, 0.1)
        containers = {name: {"container": name, "image": f"mailcow/{name.split('-')[0]}:1.0", "state": "exited" if down and name == "clamd-mailcow" else "running",
                             "started_at": datetime.fromtimestamp(now - 86400 * 9, UTC).isoformat(), "type": "info"} for name in names}
        mailboxes = [
            {"username": "alice@example.com", "active": 1, "quota": 5 * 1024 ** 3, "quota_used": int(fake.walk("mailcow-a", tick, 3.0, 4.7) * 1024 ** 3)},
            {"username": "bob@example.com", "active": 1, "quota": 5 * 1024 ** 3, "quota_used": int(fake.walk("mailcow-b", tick, 0.6, 1.3) * 1024 ** 3)},
            {"username": "carol@example.net", "active": 1, "quota": 2 * 1024 ** 3, "quota_used": 410 * 1024 ** 2},
            {"username": "old@example.net", "active": 0, "quota": 0, "quota_used": 90 * 1024 ** 2},
        ]
        domains = [
            {"domain_name": "example.com", "active": 1, "mboxes_in_domain": 2, "max_num_mboxes_for_domain": 10, "quota_used_in_domain": str(5 * 1024 ** 3), "backupmx": 0},
            {"domain_name": "example.net", "active": 1, "mboxes_in_domain": 2, "max_num_mboxes_for_domain": 5, "quota_used_in_domain": str(500 * 1024 ** 2), "backupmx": 0},
        ]
        if widget_kind == "queue":
            return self._queue(queue, options, now)
        if widget_kind == "containers":
            return self._containers(containers)
        if widget_kind == "mailboxes":
            return self._mailboxes(mailboxes, options)
        if widget_kind == "domains":
            return self._domains(domains)
        return self._overview(queue, containers, mailboxes, domains,
                              {"used_percent": f"{fake.walk('mailcow-disk', tick, 30, 55):.0f}%"})


ADAPTER = MailcowAdapter()
