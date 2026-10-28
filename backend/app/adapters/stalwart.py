"""Stalwart (1.0): the mail queue and why it is stuck, accounts and domains.

Stalwart 1.0 manages itself through JMAP. Every object has a type name with
an ``x:`` in front (``x:QueuedMessage``, ``x:Account``, ``x:Domain``), the
capability is ``urn:stalwart:jmap``, and one POST to ``/jmap/`` can ask for
several things at once. Measured against Stalwart 1.0.0 on 27.10.2026, the
old REST calls of 0.x (``/api/queue/messages``, ``/api/principal``) are not
read at all: an older Stalwart is told to update.

* The key is an API key made under the admin account (``x:ApiKey``), sent as
  a bearer token. It starts with ``API_``. HTTP basic authentication with it
  was refused (401), a password of the account works as basic authentication.
* ⚠️ A server that is still in bootstrap mode answers every call but the
  bootstrap one with ``forbidden``. The message is passed on as it is.
* A queued message keeps one status per recipient. ``Scheduled`` has not been
  tried yet; ``TemporaryFailure`` carries the reason (``errorType`` and
  ``errorMessage`` for a connection that failed, ``responseCode`` and
  ``responseMessage`` for a remote server that answered no), and the message
  stays in the queue until it expires. Seen: ``Scheduled``,
  ``TemporaryFailure``. Taken from the documentation and not seen:
  ``PermanentFailure``, ``Completed``.
"""

from __future__ import annotations

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
    ReadCommands,
    WidgetData,
    WidgetType,
    allowed,
    base_url,
    human_bytes,
    percent,
    status_from_percent,
)

USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
#: How many queued messages and accounts a card reads at most.
LIMIT = 200


def _ref(call: str, name: str) -> dict[str, str]:
    return {"resultOf": call, "name": name, "path": "/ids"}


def _pointer(text: str) -> str:
    """A key inside a JSON pointer: ``~`` and ``/`` are the only characters that need care."""
    return text.replace("~", "~0").replace("/", "~1")


def reason_of(status: dict[str, Any]) -> str:
    """Why a recipient has not been delivered to, in the server's own words."""
    if not isinstance(status, dict):
        return ""
    if status.get("responseMessage"):
        code = " ".join(str(one) for one in (status.get("responseCode"), status.get("responseEnhanced")) if one)
        text = " ".join(str(status["responseMessage"]).split())[:160]
        return f"{code} {text}".strip()
    if status.get("errorMessage"):
        return " ".join(str(status["errorMessage"]).split())[:160]
    return ""


def state_of(recipients: dict[str, Any]) -> str:
    """The worst thing any recipient is in: ``permanent``, ``temporary``, ``waiting`` or ``done``."""
    kinds = {str((one.get("status") or {}).get("@type") or "") for one in recipients.values() if isinstance(one, dict)}
    if "PermanentFailure" in kinds:
        return "permanent"
    if "TemporaryFailure" in kinds:
        return "temporary"
    if kinds - {"Completed"}:
        return "waiting"
    return "done"


class StalwartAdapter(Adapter):
    kind = "stalwart"
    label = "Stalwart"
    category = "other"
    description = "The mail queue with the reason a message is stuck, accounts and domains of a Stalwart mail server."
    icon = "stalwart"
    docs_url = "https://stalw.art/docs/ref/"
    #: Measured against Stalwart 1.0.0 on 27.10.2026; it stays beta until somebody confirms it on a server in use.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://stalwart:8080",
              help="The address of the web interface; the management API answers on it at /jmap/."),
        Field("token", "API key", type="password", secret=True, required=True,
              help="An API key of the administrator, starting with API_. It carries that account's rights."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "Sign in to Stalwart's web interface as the administrator and open the account's API keys.",
        "Create a key and copy it right away; Stalwart shows the secret once. It starts with API_.",
        "Needs Stalwart 1.0 or newer: older versions manage the server with a different interface.",
    )
    # The management API reloads and purges from a GET; a card reads the JMAP session.
    raw_read_commands = ReadCommands(last=allowed("session"))
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="Messages waiting in the queue and how many of them are failing, accounts and domains.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("queued", "failing"),
        ),
        WidgetType(
            kind="queue",
            label="Mail queue",
            description="Every message waiting to leave, the stuck ones first, with the reason the remote server or the connection gave.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="accounts",
            bars=True,
            label="Accounts",
            description="Users and groups with the disk they use, the fullest first, red near a quota.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="domains",
            bars=True,
            label="Domains",
            description="Every domain with the number of its accounts; a switched-off one turns the card yellow.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=900,
        ),
    )

    async def _jmap(self, config: dict[str, Any], ctx: Context, calls: list[list[Any]], cache: float = 0) -> dict[str, dict[str, Any]]:
        """One request, the answers by the id of the call that asked."""
        response = await ctx.request(
            "POST", f"{base_url(config)}/jmap/",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            json_body={"using": USING, "methodCalls": calls},
            verify=not config.get("insecure"),
        )
        if response.status_code in (401, 403):
            raise AuthFailed()
        if response.status_code >= 400:
            raise AdapterError(f"Stalwart answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the web interface, and Stalwart has to be 1.0 or newer.")
        try:
            body = response.json()
            answers = body["methodResponses"]
        except (ValueError, KeyError, TypeError) as error:
            raise AdapterError("Stalwart did not answer with JMAP.", code="not_jmap",
                               hint="The URL probably points at another service, or at a Stalwart older than 1.0.") from error
        found: dict[str, dict[str, Any]] = {}
        for name, arguments, call in answers:
            if name == "error":
                if (arguments or {}).get("type") == "forbidden":
                    raise AdapterError(str(arguments.get("description") or "Stalwart refused the call.")[:240], code="forbidden",
                                       hint="The key may lack a permission, or the server is still in its first setup.")
                raise AdapterError(str((arguments or {}).get("description") or "Stalwart refused the call.")[:240], code="jmap_error")
            found[call] = arguments or {}
        return found

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        session = await self._session(config, ctx)
        version = self._version(session)
        answers = await self._jmap(config, ctx, [["x:Domain/query", {"limit": 1, "calculateTotal": True}, "domains"]])
        return f"Stalwart {version or '?'} answers, {answers['domains'].get('total', 0)} domain(s)."

    async def _session(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/jmap/session",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=60,
        )
        if response.status_code >= 400:
            raise AdapterError(f"Stalwart answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the web interface, and Stalwart has to be 1.0 or newer.")
        try:
            body = response.json()
        except ValueError as error:
            raise AdapterError("Stalwart did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service.") from error
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _version(session: dict[str, Any]) -> str:
        """``1.0.0`` out of ``Stalwart v1.0.0``, which the session names in the sieve capability."""
        text = str(((session.get("capabilities") or {}).get("urn:ietf:params:jmap:sieve") or {}).get("implementation") or "")
        return text.rsplit(" ", 1)[-1].lstrip("v") if text else ""

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        return self._version(await self._session(config, ctx)) or None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "queue":
            answers = await self._jmap(config, ctx, [
                ["x:QueuedMessage/query", {"limit": LIMIT, "calculateTotal": True}, "queueIds"],
                ["x:QueuedMessage/get", {"#ids": _ref("queueIds", "x:QueuedMessage/query"),
                                         "properties": ["createdAt", "nextRetry", "returnPath", "recipients", "size", "flags"]}, "queue"],
            ])
            return self._queue(answers["queue"].get("list") or [], int(answers["queueIds"].get("total") or 0), options)
        if widget_kind in ("accounts", "domains"):
            answers = await self._jmap(config, ctx, [
                ["x:Domain/get", {"properties": ["name", "enable", "description", "catchAllAddress"]}, "domains"],
                ["x:Account/query", {"limit": LIMIT, "calculateTotal": True}, "accountIds"],
                ["x:Account/get", {"#ids": _ref("accountIds", "x:Account/query"),
                                   "properties": ["@type", "name", "domainId", "emailAddress", "quotas", "usedDiskQuota"]}, "accounts"],
            ])
            domains = answers["domains"].get("list") or []
            accounts = answers["accounts"].get("list") or []
            if widget_kind == "domains":
                return self._domains(domains, accounts, int(answers["accountIds"].get("total") or len(accounts)))
            return self._accounts(accounts, int(answers["accountIds"].get("total") or len(accounts)), options)
        answers = await self._jmap(config, ctx, [
            ["x:Domain/query", {"limit": 1, "calculateTotal": True}, "domainIds"],
            ["x:Account/query", {"limit": 1, "calculateTotal": True}, "accountIds"],
            ["x:QueuedMessage/query", {"limit": LIMIT, "calculateTotal": True}, "queueIds"],
            ["x:QueuedMessage/get", {"#ids": _ref("queueIds", "x:QueuedMessage/query"), "properties": ["nextRetry", "recipients"]}, "queue"],
        ])
        queued = int(answers["queueIds"].get("total") or 0)
        failing = sum(1 for message in answers["queue"].get("list") or []
                      if state_of(message.get("recipients") or {}) in ("temporary", "permanent"))
        return WidgetData(
            status="warn" if failing else "ok",
            primary={"label": "Queued", "value": queued},
            secondary=[
                {"label": "Failing", "value": failing},
                {"label": "Accounts", "value": int(answers["accountIds"].get("total") or 0)},
                {"label": "Domains", "value": int(answers["domainIds"].get("total") or 0)},
            ],
            metrics={"queued": float(queued), "failing": float(failing)},
        )

    def _queue(self, messages: list[dict[str, Any]], total: int, options: dict[str, Any]) -> WidgetData:
        rank = {"permanent": 0, "temporary": 1, "waiting": 2, "done": 3}
        rows = []
        for message in messages:
            recipients = message.get("recipients") if isinstance(message.get("recipients"), dict) else {}
            state = state_of(recipients)
            stuck = next((one for one in recipients.values()
                          if isinstance(one, dict) and str((one.get("status") or {}).get("@type")) in ("TemporaryFailure", "PermanentFailure")), None)
            address = next(iter(recipients), "?")
            more = len(recipients) - 1
            parts = [reason_of((stuck or {}).get("status") or {}) or ("Waiting for its turn" if state == "waiting" else "")]
            tries = int((stuck or {}).get("retryCount") or 0)
            if tries:
                parts.append(f"{tries} tries")
            if message.get("size"):
                parts.append(human_bytes(message["size"]))
            identifier = str(message.get("id") or "")
            rows.append((rank[state], {
                "title": f"{message.get('returnPath') or '?'} → {address}" + (f" +{more}" if more > 0 else ""),
                "subtitle": " · ".join(part for part in parts if part),
                "status": "bad" if state == "permanent" else "warn" if state == "temporary" else "ok",
                "value": "Failing" if state in ("temporary", "permanent") else "Waiting" if state == "waiting" else "Delivered",
                "actions": [
                    Action(id="retry", label="Retry now", icon="refresh-cw", params={"id": identifier}),
                    Action(id="remove", label="Remove", icon="trash-2", confirm=True, danger=True, params={"id": identifier}),
                ] if identifier else [],
            }))
        rows.sort(key=lambda row: row[0])
        items = [item for _rank, item in rows][: int(options.get("limit") or 10)]
        states = {item["status"] for item in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items,
            secondary=[{"label": "Queued", "value": total}],
        )

    def _accounts(self, accounts: list[dict[str, Any]], total: int, options: dict[str, Any]) -> WidgetData:
        rows = []
        for account in accounts:
            used = int(account.get("usedDiskQuota") or 0)
            quota = (account.get("quotas") or {}).get("maxDiskQuota") if isinstance(account.get("quotas"), dict) else None
            share = percent(used, quota) if quota else None
            group = account.get("@type") == "Group"
            rows.append({
                "title": str(account.get("emailAddress") or account.get("name") or "?"),
                "subtitle": " · ".join(part for part in (
                    "Group" if group else "",
                    f"{human_bytes(used)} of {human_bytes(quota)}" if quota else human_bytes(used)) if part),
                "status": status_from_percent(share) if share is not None else "ok",
                "value": used,
            })
        rows.sort(key=lambda row: (-row["value"], row["title"]))
        states = {row["status"] for row in rows}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=rows[: int(options.get("limit") or 10)],
            secondary=[{"label": "Accounts", "value": total}],
        )

    def _domains(self, domains: list[dict[str, Any]], accounts: list[dict[str, Any]], total: int) -> WidgetData:
        counted: dict[str, int] = {}
        for account in accounts:
            counted[str(account.get("domainId"))] = counted.get(str(account.get("domainId")), 0) + 1
        rows = []
        for domain in domains:
            enabled = domain.get("enable") is not False
            rows.append({
                "title": str(domain.get("name") or "?"),
                "subtitle": " · ".join(part for part in (
                    str(domain.get("description") or ""), "Switched off" if not enabled else "",
                    "Catch-all" if domain.get("catchAllAddress") else "") if part),
                "status": "ok" if enabled else "warn",
                "value": counted.get(str(domain.get("id")), 0),
            })
        rows.sort(key=lambda row: (row["status"] == "ok", row["title"]))
        return WidgetData(
            status="warn" if any(row["status"] == "warn" for row in rows) else "ok",
            items=rows,
            secondary=[{"label": "Domains", "value": len(rows)}, {"label": "Accounts", "value": total}],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        identifier = str(params.get("id") or "")
        if not identifier or not identifier.isalnum():
            raise AdapterError("That is not a queued message.", code="bad_param")
        if action_id == "remove":
            answers = await self._jmap(config, ctx, [["x:QueuedMessage/set", {"destroy": [identifier]}, "set"]])
            if identifier in (answers["set"].get("notDestroyed") or {}):
                raise AdapterError("Stalwart did not remove the message.", code="not_removed",
                                   hint="It may have left the queue in the meantime.")
            return "Message removed from the queue."
        if action_id == "retry":
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            got = await self._jmap(config, ctx, [["x:QueuedMessage/get", {"ids": [identifier], "properties": ["recipients"]}, "one"]])
            found = (got["one"].get("list") or [])
            if not found:
                raise AdapterError("That message is no longer in the queue.", code="gone")
            patch: dict[str, Any] = {"nextRetry": now}
            for address, recipient in (found[0].get("recipients") or {}).items():
                if str((recipient.get("status") or {}).get("@type")) != "Completed":
                    patch[f"recipients/{_pointer(address)}/retryDue"] = now
            answers = await self._jmap(config, ctx, [["x:QueuedMessage/set", {"update": {identifier: patch}}, "set"]])
            if identifier in (answers["set"].get("notUpdated") or {}):
                raise AdapterError("Stalwart did not accept the new time.", code="not_updated")
            return "The message will be tried again now."
        raise AdapterError("Stalwart has no such action.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        stuck = fake.flicker("stalwart-queue", tick, 0.5)
        messages = [
            {"id": "m1", "returnPath": "alice@example.com", "size": 48_000, "nextRetry": "2026-10-27T18:00:00Z",
             "recipients": {"carol@example.net": {"retryCount": 3, "status": {
                 "@type": "TemporaryFailure", "responseCode": 451, "responseEnhanced": "4.7.1",
                 "responseMessage": "Greylisted, try again later"}}}},
            {"id": "m2", "returnPath": "bob@example.com", "size": 9_000, "nextRetry": "2026-10-27T18:05:00Z",
             "recipients": {"dave@example.org": {"retryCount": 0, "status": {"@type": "Scheduled"}},
                            "erin@example.org": {"retryCount": 0, "status": {"@type": "Scheduled"}}}},
        ]
        if stuck:
            messages.append({"id": "m3", "returnPath": "team@example.com", "size": 120_000, "nextRetry": "2026-10-27T18:10:00Z",
                             "recipients": {"frank@example.net": {"retryCount": 5, "status": {
                                 "@type": "TemporaryFailure", "errorType": "connectionError",
                                 "errorMessage": "I/O error: Connection timed out (os error 110)"}}}})
        if widget_kind == "queue":
            return self._queue(messages, len(messages), options)
        accounts = [
            {"@type": "User", "name": "alice", "emailAddress": "alice@example.com", "domainId": "d1",
             "quotas": {"maxDiskQuota": 5 * 1024 ** 3}, "usedDiskQuota": int(fake.walk("stalwart-a", tick, 3.0, 4.6) * 1024 ** 3)},
            {"@type": "User", "name": "bob", "emailAddress": "bob@example.com", "domainId": "d1",
             "quotas": {"maxDiskQuota": 5 * 1024 ** 3}, "usedDiskQuota": int(fake.walk("stalwart-b", tick, 0.8, 1.4) * 1024 ** 3)},
            {"@type": "Group", "name": "team", "emailAddress": "team@example.com", "domainId": "d1", "quotas": {}, "usedDiskQuota": 380 * 1024 ** 2},
            {"@type": "User", "name": "carol", "emailAddress": "carol@example.net", "domainId": "d2", "quotas": {}, "usedDiskQuota": 90 * 1024 ** 2},
        ]
        if widget_kind == "accounts":
            return self._accounts(accounts, len(accounts), options)
        domains = [{"id": "d1", "name": "example.com", "enable": True, "description": "Main"},
                   {"id": "d2", "name": "example.net", "enable": True, "description": "Family"}]
        if widget_kind == "domains":
            return self._domains(domains, accounts, len(accounts))
        failing = sum(1 for message in messages if state_of(message["recipients"]) == "temporary")
        return WidgetData(
            status="warn" if failing else "ok",
            primary={"label": "Queued", "value": len(messages)},
            secondary=[{"label": "Failing", "value": failing}, {"label": "Accounts", "value": len(accounts)},
                       {"label": "Domains", "value": len(domains)}],
            metrics={"queued": float(len(messages)), "failing": float(failing)},
        )


ADAPTER = StalwartAdapter()
