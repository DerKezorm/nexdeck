"""nexmail: the mail client of the nexapps family, read through its API keys.

⚠️ Built against the contract nexmail's own session wrote down for 0.17.0,
before that release existed, so ``beta`` until a card has read a real
installation. Everything is a GET and nothing here can change a mailbox.

Three things the contract says that shape the cards:

- A key carries its own rights in ``GET /api/v1/me``: ``key.scope`` is
  ``count`` or ``headers``, and ``mailboxes`` are exactly the ones its owner
  shared on the key. The cards build on that answer, not on a guess, the same
  way the Nexview cards build on ``darf``.
- A key of scope ``count`` is refused by ``/messages/latest`` with 403. That
  is a decision somebody made in nexmail, not a fault, so the list card says
  it as a hint and is not offered for such a key at all.
- ``status: sign_in_failed`` on a mailbox means the mail server rejects the
  stored password and the number is from before. It must not look like a
  quiet inbox.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
)

#: The scope that may read sender and subject. The other one, ``count``,
#: may read numbers and nothing else.
MAY_READ_HEADERS = "headers"

#: How many messages ``/messages/latest`` hands out at most; nexmail answers
#: 422 outside 1..20.
MOST = 20

#: The hint on a list card whose key may only count, and the reason the
#: library gives for not adding one.
COUNTS_ONLY = ("This key may only read counts. Edit it in nexmail and choose "
               "“Count, sender and subject” to see the latest mail.")

#: nexmail's refusals by the identifier in ``detail``, as a sentence that says
#: what to do and a code the interface translates by.
REFUSALS: dict[str, tuple[str, str]] = {
    "api_schluessel_fehlt": (
        "nexmail received no API key. Enter the key in this connection.",
        "nexmail_key_missing",
    ),
    "api_schluessel_ungueltig": (
        "nexmail does not know this key, or it was revoked. Create a new key in nexmail "
        "under Settings → API keys and enter it in this connection.",
        "nexmail_key_invalid",
    ),
    "api_schluessel_abgeschaltet": (
        "API keys are turned off on this nexmail installation. The operator of nexmail turns them "
        "on under Settings → API keys.",
        "nexmail_keys_off",
    ),
    "api_schluessel_nur_anzahl": (COUNTS_ONLY, "nexmail_counts_only"),
    "postfach_unbekannt": (
        "A mailbox picked on this card is no longer shared with this key. Pick the mailboxes "
        "again in the card's settings, or share the mailbox on the key in nexmail.",
        "nexmail_mailbox_unknown",
    ),
}
BAD_LIMIT = ("nexmail refused the number of messages. Pick between 1 and 20.", "nexmail_bad_limit")


def _refused(identifier: str) -> AdapterError:
    message, code = REFUSALS[identifier]
    return AdapterError(message, code=code)


def _mailbox_ids(options: dict[str, Any]) -> list[str]:
    """The mailboxes picked on a card, as strings. Nothing picked means all of them."""
    picked = options.get("mailboxes")
    if not isinstance(picked, list):
        return []
    return [str(one) for one in picked if str(one).strip()]


def _limit(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("limit") or 5)
    except (TypeError, ValueError):
        wanted = 5
    return max(1, min(MOST, wanted))


def _sender(message: dict[str, Any]) -> str:
    return str(message.get("from_name") or "").strip() or str(message.get("from_address") or "").strip() or "?"


def _unread_row(mailbox: dict[str, Any]) -> dict[str, Any]:
    failed = mailbox.get("status") == "sign_in_failed"
    row: dict[str, Any] = {
        "id": str(mailbox.get("id")),
        "title": str(mailbox.get("name") or mailbox.get("address") or "?"),
        "value": int(mailbox.get("unread") or 0),
        "status": "bad" if failed else "ok",
    }
    # ⚠️ The word goes into the subtitle, not the value: the value is drawn as
    # it comes, and "Sign-in failed" on the right would stay English on a
    # German board.
    address = str(mailbox.get("address") or "")
    row["subtitle"] = " · ".join(part for part in ("Sign-in failed" if failed else "", address) if part)
    return row


def _message_row(message: dict[str, Any], base: str, several: bool) -> dict[str, Any]:
    unread = bool(message.get("unread"))
    subject = str(message.get("subject") or "").strip() or "(no subject)"
    row: dict[str, Any] = {
        "id": str(message.get("id")),
        "title": _sender(message),
        # With one mailbox its name on every row says nothing.
        "subtitle": f"{subject} · {message.get('mailbox')}" if several and message.get("mailbox") else subject,
        "value": ago(message.get("date")),
        "status": "ok" if unread else "unknown",
        "emphasis": unread,
    }
    if message.get("id") is not None:
        # Opens exactly this message in a window of its own.
        row["url"] = f"{base}/?{httpx.QueryParams({'nachricht': str(message['id'])})}"
    return row


class NexmailAdapter(Adapter):
    kind = "nexmail"
    label = "nexmail"
    category = "other"
    description = "Unread mail and the latest senders and subjects from nexmail, through a read-only API key."
    icon = "nexmail"
    docs_url = "https://nexmail.nexapps.dev"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://mail.example.com",
              help="The address nexmail is reached at, with its sub-path if it has one."),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="A key from nexmail under Settings → API keys. It shows only the mailboxes shared on it; "
                   "sender and subject need a key that may read them, not only counts."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="unread",
            label="Unread mail",
            description="Unread mail in the inbox, in total and for each mailbox.",
            renderer="list",
            default_size=(2, 2),
            refresh_seconds=60,
            metrics=("unread",),
            options=(Field("mailboxes", "Mailboxes", type="choices", default=[],
                           help="Nothing picked means every mailbox shared on the key."),),
        ),
        WidgetType(
            kind="latest",
            label="Latest mail",
            description="Sender and subject of the newest mail in the inbox, unread ones highlighted.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(
                Field("mailboxes", "Mailboxes", type="choices", default=[],
                      help="Nothing picked means every mailbox shared on the key."),
                Field("limit", "Entries", type="number", default=5, help="Between 1 and 20."),
                Field("unread_only", "Only unread mail", type="bool", default=False),
            ),
        ),
    )
    bars_widgets = True

    # -- talking to nexmail --------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *,
                   params: Any = None, cache: float = 30) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", params=params, headers=self._headers(config),
            verify=not config.get("insecure"), cache_seconds=cache,
            # ⚠️ Not turned into "the credentials were rejected". nexmail says
            # which of four things it is, and two of them (keys switched off,
            # a key that may only count) are fixed somewhere else entirely.
            auth_errors=False,
        )
        if response.status_code >= 400:
            message, code = self._refusal(response)
            raise AdapterError(message, code=code)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("nexmail did not answer with data. The URL probably points at a login page "
                               "or at something else.", code="not_json") from error
        if not isinstance(answer, dict):
            raise AdapterError("nexmail did not answer in the shape this card knows.", code="not_json")
        return answer

    @staticmethod
    def _refusal(response: httpx.Response) -> tuple[str, str]:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail in REFUSALS:
            return REFUSALS[detail]
        if response.status_code == 422:
            return BAD_LIMIT
        if response.status_code == 404:
            return ("nexmail has no API at this address. Check the URL, including a sub-path, "
                    "and that nexmail is 0.17.0 or newer.", "http_error")
        return (f"nexmail answered with HTTP {response.status_code}.", "http_error")

    async def _me(self, config: dict[str, Any], ctx: Context, cache: float = 300) -> dict[str, Any]:
        """Who the key belongs to, what it may read and which mailboxes it sees."""
        return await self._get(config, ctx, "/api/v1/me", cache=cache)

    @staticmethod
    def _shared(me: dict[str, Any]) -> list[dict[str, Any]]:
        return [one for one in me.get("mailboxes") or [] if isinstance(one, dict) and one.get("id") is not None]

    @staticmethod
    def _scope(me: dict[str, Any]) -> str:
        return str((me.get("key") or {}).get("scope") or "")

    # -- hooks ---------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._me(config, ctx, cache=0)
        count = len(self._shared(me))
        user = me.get("user") or {}
        who = str(user.get("display_name") or user.get("username") or "?")
        boxes = f"{count} mailbox" if count == 1 else f"{count} mailboxes"
        if count == 0:
            return f"nexmail answers. The key of {who} has no mailbox shared on it, so the cards stay empty."
        if self._scope(me) == MAY_READ_HEADERS:
            return f"nexmail answers. The key of {who} reads {boxes}, with sender and subject."
        # ⚠️ Said at setup, not discovered on the board.
        return f"nexmail answers. The key of {who} reads {boxes}, counts only, so the latest mail card is not offered."

    async def barred(self, widget_kind: str, config: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "latest":
            return ""
        me = await self._me(config, ctx)
        return "" if self._scope(me) == MAY_READ_HEADERS else COUNTS_ONLY

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field == "mailboxes":
            return [(str(one["id"]), str(one.get("name") or one.get("address") or one["id"]))
                    for one in self._shared(await self._me(config, ctx, cache=60))]
        return await super().choices(field, config, ctx)

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field == "mailboxes":
            return [(str(one["id"]), one["name"]) for one in DEMO_MAILBOXES]
        return super().demo_choices(field)

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "unread":
            return await self._unread(config, options, ctx)
        if widget_kind == "latest":
            return await self._latest(config, options, ctx)
        raise AdapterError("This adapter has no such widget.", code="no_such_widget")

    async def _unread(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        summary = await self._get(config, ctx, "/api/v1/summary")
        mailboxes = [one for one in summary.get("mailboxes") or [] if isinstance(one, dict)]
        picked = _mailbox_ids(options)
        if picked:
            mailboxes = [one for one in mailboxes if str(one.get("id")) in picked]
            if not mailboxes:
                raise _refused("postfach_unbekannt")
        return self._unread_data(mailboxes, whole=not picked, total=summary.get("unread"))

    @staticmethod
    def _unread_data(mailboxes: list[dict[str, Any]], *, whole: bool, total: Any = None) -> WidgetData:
        # The sum nexmail gives is for every shared mailbox; with a pick it
        # is the sum of the picked ones, or the headline would disagree with
        # the rows under it.
        unread = int(total) if whole and isinstance(total, int) else sum(int(one.get("unread") or 0) for one in mailboxes)
        failed = [one for one in mailboxes if one.get("status") == "sign_in_failed"]
        meta: dict[str, Any] = {"headline": True, "empty": "No mailbox is shared on this key."}
        if failed:
            meta["status_reason"] = f"{len(failed)} mailbox(es) cannot sign in, their numbers are old"
            meta["notice"] = ("The mail server rejects the password of a mailbox, so its number is old. "
                              "Sign in again in nexmail.")
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Unread", "value": unread},
            items=[_unread_row(one) for one in mailboxes],
            metrics={"unread": float(unread)},
            meta=meta,
        )

    async def _latest(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        me = await self._me(config, ctx)
        if self._scope(me) != MAY_READ_HEADERS:
            # ⚠️ A hint, not an error: the key does what its owner chose.
            return WidgetData(status="unknown", meta={"notice": COUNTS_ONLY, "empty": "Nothing to show"})
        shared = {str(one["id"]) for one in self._shared(me)}
        picked = _mailbox_ids(options)
        if picked:
            # ⚠️ Narrowed to what the key still sees before asking. A mailbox
            # taken off the key later would otherwise turn the whole card into
            # nexmail's 404, although the other picks are fine.
            picked = [one for one in picked if one in shared]
            if not picked:
                raise _refused("postfach_unbekannt")
        params: list[tuple[str, str]] = [("mailbox", one) for one in picked]
        params += [("limit", str(_limit(options))), ("unread_only", "true" if options.get("unread_only") else "false")]
        answer = await self._get(config, ctx, "/api/v1/messages/latest", params=params)
        messages = [one for one in answer.get("messages") or [] if isinstance(one, dict)]
        several = len(picked) != 1 and len(shared) > 1
        base = base_url(config)
        return WidgetData(
            status="ok",
            items=[_message_row(one, base, several) for one in messages],
            meta={"empty": "No unread mail." if options.get("unread_only") else "No mail in the inbox."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        picked = _mailbox_ids(options)
        mailboxes = [dict(one) for one in DEMO_MAILBOXES if not picked or str(one["id"]) in picked]
        if widget_kind == "unread":
            for one in mailboxes:
                one["unread"] = int(one["unread"]) + (tick // 120) % 3
            return self._unread_data(mailboxes, whole=False)
        shown = [str(one["id"]) for one in mailboxes]
        now = time.time()
        # Ages rather than dates, so the demo never turns into last month.
        messages = [{**one, "date": now - one["minutes_ago"] * 60} for one in DEMO_MESSAGES
                    if str(one["mailbox_id"]) in shown]
        if options.get("unread_only"):
            messages = [one for one in messages if one["unread"]]
        return WidgetData(
            status="ok",
            items=[_message_row(one, "https://mail.example.com", len(shown) > 1) for one in messages][: _limit(options)],
            meta={"empty": "No unread mail." if options.get("unread_only") else "No mail in the inbox."},
        )


DEMO_MAILBOXES: list[dict[str, Any]] = [
    {"id": "1", "name": "Home", "address": "home@example.com", "unread": 4, "status": "ok"},
    {"id": "2", "name": "Work", "address": "work@example.com", "unread": 11, "status": "ok"},
    {"id": "3", "name": "Club", "address": "club@example.com", "unread": 2, "status": "sign_in_failed"},
]
DEMO_MESSAGES: list[dict[str, Any]] = [
    {"id": 901, "mailbox_id": "2", "mailbox": "Work", "from_name": "Build server", "from_address": "ci@example.com",
     "subject": "Nightly build passed", "minutes_ago": 6, "unread": True, "flagged": False},
    {"id": 902, "mailbox_id": "1", "mailbox": "Home", "from_name": "", "from_address": "parcel@example.com",
     "subject": "Your parcel is on its way", "minutes_ago": 50, "unread": True, "flagged": False},
    {"id": 903, "mailbox_id": "2", "mailbox": "Work", "from_name": "Team calendar", "from_address": "calendar@example.com",
     "subject": "Planning moved to Thursday", "minutes_ago": 900, "unread": False, "flagged": True},
    {"id": 904, "mailbox_id": "3", "mailbox": "Club", "from_name": "Club board", "from_address": "board@example.com",
     "subject": "Summer party", "minutes_ago": 1400, "unread": False, "flagged": False},
    {"id": 905, "mailbox_id": "1", "mailbox": "Home", "from_name": "Library", "from_address": "library@example.com",
     "subject": "Two books are due next week", "minutes_ago": 2900, "unread": False, "flagged": False},
]


ADAPTER = NexmailAdapter()
