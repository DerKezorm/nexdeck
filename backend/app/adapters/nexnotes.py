"""nexnotes: pinned notes and one note or checklist, read and ticked off through its API tokens.

Written against nexnotes' ``docs/api.md`` (branch ``main``, 22.11.2026) and its ``/api/v1``: ``GET /me``,
``/dashboard``, ``/notes``, ``/notes/{id}`` and ``POST /notes/{id}/items/{index}``, the five routes of its card.

- The token goes in ``Authorization: Bearer``, never in the address. An API token starts with ``nn_api_``; an older
  key for the card (``nn_deck_``) reaches these five routes and nothing else, which is all the cards ask of it.
  nexnotes refuses any request that carries an ``Origin`` header (403 ``origin_refused``), so it is only ever called
  from nexdeck's server.
- The API is on from the start; nexnotes' operator can switch it off (403 ``api_off``), and tokens work again once it
  is back on. A wrong, run-out, revoked or blocked token answers 401 ``token_invalid``. More than 600 requests a
  minute answer 429 ``slow_down``, twenty wrong tokens from one sender 429 ``too_many_attempts``.
- ``/me`` says ``app: nexnotes`` and the token's ``level``. Ticking off needs ``write`` and a note the account may
  write (``can_check`` of the note); without either the card offers no ticking and says why.
- A locked note never leaves nexnotes, and nothing here is built for one. A note that went (deleted, locked, its
  sharing ended) is said on the card without anything of what it showed before.
- Both cards ask every 30 seconds. The answer's ``stamp`` changes with every change the card shows; the screen draws
  anew only then. When nexnotes cannot be reached, the card keeps the last state with a note of when it was read
  (``as_of``), and nothing can be ticked until it answers again.
- Ticking sends the item's text as it was read: an item that says something else by now is left alone (409
  ``item_changed``) and the card reads the note anew.

What the cards leave out on purpose: writing, formatting, attachments, tags and the trash.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    path_segment,
)
from .nexapp_base import NexappApi, code_of, count_of, epoch_of

#: Both cards ask this often; nexnotes' ``stamp`` tells whether anything changed.
REFRESH_SECONDS = 30
#: How long the token's level is believed: it changes only when the token is made anew.
LEVEL_SECONDS = 300
#: The notes offered in a card's settings, newest change first.
CHOICES = 200
#: Pinned notes and checklist items a card shows at most.
MOST = 50

#: What a nexnotes refusal of these five routes means, said for the card. The family's walls (``origin_refused``,
#: ``api_off``, ``token_invalid``, the rates) are ``NexappApi._refuse``'s. ``forget``: the card shows nothing of
#: what it showed before, because the note is not to be seen any more.
REFUSALS: dict[str, tuple[str, str, str, bool]] = {
    "token_card_only": ("This older key of nexnotes reaches the card's own routes only.", "wrong_kind",
                        "Make an API token under Settings > Connections > API tokens in nexnotes.", False),
    "token_reads_only": ("This token may only read; ticking off needs an API token with Read and write.", "read_only",
                         "Make an API token with Read and write under Settings > Connections > API tokens in nexnotes.", False),
    "not_allowed": ("This note is shared with you to read only; it cannot be ticked off here.", "not_allowed", "", False),
    "not_found": ("nexnotes has no such note, or this token may not see it.", "no_note",
                  "It was deleted, its sharing ended, or it lies outside the token's folders. Pick a note again in the card's settings.", True),
    "note_locked": ("This note is locked in the vault; the card shows nothing of it.", "note_locked",
                    "Unlock it in nexnotes, or pick another note in the card's settings.", True),
    "note_trashed": ("This note is in the trash.", "note_trashed",
                     "Bring it back in nexnotes, or pick another note in the card's settings.", True),
    "item_changed": ("This item changed in nexnotes meanwhile; the card shows it anew.", "item_changed", "", False),
    "invalid_input": ("nexnotes could not take this request.", "bad_param", "", False),
}


class NexnotesAdapter(NexappApi, Adapter):
    kind = "nexnotes"
    label = "nexnotes"
    category = "other"
    description = "Quick notes and checklists in nexnotes: the pinned notes, or one note or checklist that can be ticked off right on the card."
    icon = "nexnotes"
    #: Until it has run against an instance in use.
    beta = True
    #: Empty while nexnotes' repository is private: a link there would end at a 404 for everybody else.
    docs_url = ""
    app = "nexnotes"
    thing = "token"
    #: ``/me`` names the app and its ``features``; the family's other ``features`` (nextasks') come without ``app``.
    own_fields = ("app", "features")
    where_on = "nexnotes' operator switches it on under Settings > Server > General > API for members"
    where_make = "Make an API token under Settings > Connections > API tokens in nexnotes; Read only fills the cards, Read and write also ticks off."
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexnotes:8570"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="Settings > Connections > API tokens > New API token in nexnotes. It starts with nn_api_; Read only fills the cards, Read and write also ticks items off. An older key for nexdeck (nn_deck_) works too."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="pinned",
            label="Pinned notes",
            description="The notes pinned in nexnotes, newest change first: title, first line and how far their checklists are. A tap opens the note.",
            renderer="checklist",
            default_size=(3, 3),
            refresh_seconds=REFRESH_SECONDS,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="note",
            label="A note or checklist",
            description="One note of nexnotes: its checklist with the open items first and how many are done, or its first lines. With a token that may write, a tap ticks an item off.",
            renderer="checklist",
            default_size=(3, 4),
            refresh_seconds=REFRESH_SECONDS,
            options=(
                Field("note", "Note", type="choices", required=True,
                      help="The notes this token sees, newest change first. Locked notes are never offered."),
                Field("limit", "Entries", type="number", default=12),
                Field("checked", "Show ticked items", type="bool", default=True,
                      help="Below the open ones, struck through."),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    def _refuse(self, response: Any, missing: tuple[str, str, str] | None) -> None:
        refusal = REFUSALS.get(code_of(response))
        if refusal:
            message, code, hint, forget = refusal
            raise AdapterError(message, code=code, hint=hint, forget=forget)
        if response.status_code >= 500:
            # A proxy in front of a nexnotes that is down answers 502 or 503: that is not reachable, not a refusal.
            raise AdapterError(f"nexnotes cannot be reached right now (HTTP {response.status_code}).", code="unreachable",
                               hint="Check whether nexnotes runs.")
        super()._refuse(response, missing)

    async def _post(self, config: dict[str, Any], ctx: Context, path: str, body: dict[str, Any]) -> Any:
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1{path}", json_body=body, auth_errors=False,
            headers={"Authorization": f"Bearer {config.get(self.secret) or ''}", "Accept": "application/json"},
            verify=not config.get("insecure"),
        )
        self._refuse(response, None)
        try:
            return response.json()
        except ValueError:
            return {}

    async def _account(self, config: dict[str, Any], ctx: Context, *, cache: int = LEVEL_SECONDS) -> dict[str, Any]:
        """``/me``, refused when it is not nexnotes that answers."""
        me = await self._me(config, ctx) if cache == 0 else await self._get(config, ctx, "/me", cache=cache)
        if not isinstance(me, dict) or me.get("app") != "nexnotes":
            raise AdapterError(
                "This address answers, but not as nexnotes.", code="wrong_app",
                hint="Enter the address of nexnotes and a token made there; another app answers here.",
            )
        return me

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._account(config, ctx, cache=0)
        who = me.get("display_name") or me.get("name") or "?"
        does = "reads and ticks off" if level_of(me) == "write" else "reads"
        folders = me.get("folders")
        sees = "all notes" if folders is None else f"{len(folders)} folder{'' if len(folders) == 1 else 's'}" if isinstance(folders, list) else "all notes"
        return f"nexnotes {me.get('version') or '?'} answers; the token of {who} {does} and sees {sees}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "note":
            wanted = _note_id(options)
            answer = await self._get(config, ctx, f"/notes/{wanted}", {"markdown": "false"}, cache=0)
            note = self._expect(answer, "items", "can_check", "stamp")
            me = await self._account(config, ctx)
            return note_of(note, level_of(me) == "write", _limit(options, 12), _on(options, "checked"), base)
        answer = await self._get(config, ctx, "/dashboard", {"limit": _limit(options, 8)}, cache=0, missing=(
            "This nexnotes has no dashboard route yet; it needs a newer version.", "too_old",
            "Update nexnotes. Or the address has a path: use the one you open nexnotes with."))
        return pinned_of(self._expect(answer, "pinned", "stamp"), base)

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "note":
            return await super().choices(field, config, ctx)
        answer = await self._get(config, ctx, "/notes", {"limit": CHOICES}, cache=60)
        notes = answer.get("notes") if isinstance(answer, dict) else None
        return [(str(one["id"]), _note_label(one)) for one in notes or []
                if isinstance(one, dict) and one.get("id") and not one.get("locked")]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [(one["id"], _note_label(one)) for one in DEMO_NOTES] if field == "note" else []

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "check":
            raise AdapterError("This widget has no such action.", code="no_such_action")
        note = path_segment(params.get("note"), "The note")
        try:
            index = int(params.get("index"))
        except (TypeError, ValueError):
            raise AdapterError("The item is not a number this can be used with.", code="bad_param") from None
        if index < 0:
            raise AdapterError("The item is not a number this can be used with.", code="bad_param")
        checked = params.get("checked") is True
        try:
            await self._post(config, ctx, f"/notes/{note}/items/{index}", {"checked": checked, "text": str(params.get("text") or "")})
        finally:
            # The note is read anew right after, ticked or not: a changed item has to show as it is now.
            ctx.forget_answers()
        return "Ticked off." if checked else "Opened again."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "http://nexnotes.example.com"
        if widget_kind == "note":
            bought = fake.flicker("nexnotes-milk", tick, 0.5)
            items = [
                {"index": 0, "text": "Milk", "checked": bought, "depth": 0},
                {"index": 1, "text": "Bread", "checked": True, "depth": 0},
                {"index": 2, "text": "Apples", "checked": False, "depth": 0},
                {"index": 3, "text": "Coffee", "checked": False, "depth": 0},
                {"index": 4, "text": "The dark roast", "checked": False, "depth": 1},
                {"index": 5, "text": "Washing-up liquid", "checked": True, "depth": 0},
            ]
            done = sum(1 for item in items if item["checked"])
            return note_of({
                "id": "demo-shopping", "title": "Shopping", "link": f"{base}/notes/demo-shopping", "can_check": True,
                "tasks": {"done": done, "total": len(items)}, "items": items, "more_items": 0, "lines": [],
                "stamp": f"demo-{bought}", "as_of": None,
            }, True, _limit(options, 12), _on(options, "checked"), base)
        pinned = [
            {"id": "demo-shopping", "title": "Shopping", "first_line": "Milk", "tasks": {"done": 2, "total": 6}, "link": f"{base}/notes/demo-shopping"},
            {"id": "demo-trip", "title": "Packing for the trip", "first_line": "Passports", "tasks": {"done": 9, "total": 14}, "link": f"{base}/notes/demo-trip", "owner": "Sam"},
            {"id": "demo-wifi", "title": "Guest wifi", "first_line": "The password is on the fridge.", "tasks": None, "link": f"{base}/notes/demo-wifi"},
            {"id": "demo-ideas", "title": "Ideas for the garden", "first_line": "Raised beds along the fence", "tasks": None, "link": f"{base}/notes/demo-ideas"},
        ]
        return pinned_of({"pinned": pinned[:_limit(options, 8)], "more": max(0, len(pinned) - _limit(options, 8)),
                          "link": base, "stamp": "demo", "as_of": None}, base)


#: The notes the demo offers in the card's settings.
DEMO_NOTES = (
    {"id": "demo-shopping", "title": "Shopping", "tasks": {"done": 2, "total": 6}},
    {"id": "demo-trip", "title": "Packing for the trip", "tasks": {"done": 9, "total": 14}, "owner": "Sam"},
    {"id": "demo-wifi", "title": "Guest wifi", "tasks": None},
)


def level_of(me: dict[str, Any]) -> str:
    """The token's level: ``/me`` names it at the top; an answer that nests it under ``token`` is read too."""
    token = me.get("token") if isinstance(me.get("token"), dict) else {}
    return str(me.get("level") or token.get("level") or "read")


def _note_id(options: dict[str, Any]) -> str:
    wanted = str(options.get("note") or "").strip()
    if not wanted:
        raise AdapterError("Pick a note in the card's settings.", code="bad_param")
    return path_segment(wanted, "The note")


def _note_label(one: dict[str, Any]) -> str:
    title = str(one.get("title") or "").strip() or "Untitled note"
    tasks = one.get("tasks") if isinstance(one.get("tasks"), dict) else None
    owner = str(one.get("owner") or "").strip()
    return " · ".join(part for part in (
        title,
        f"{count_of(tasks.get('done'))}/{count_of(tasks.get('total'))}" if tasks else "",
        owner,
    ) if part)


def _limit(options: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(MOST, int(options.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _on(options: dict[str, Any], name: str) -> bool:
    value = options.get(name)
    return True if value is None or value == "" else value is True or str(value).lower() in ("true", "1", "yes")


def _progress(tasks: Any) -> tuple[int, int] | None:
    if not isinstance(tasks, dict) or not count_of(tasks.get("total")):
        return None
    return count_of(tasks.get("done")), count_of(tasks.get("total"))


def _held(answer: dict[str, Any]) -> dict[str, Any]:
    """What both cards keep in ``meta``: the stamp that says when to draw anew, and the moment of the answer.

    ``offline_note`` asks the collector to keep this state, with a quiet note, while nexnotes cannot be reached.
    """
    return {"stamp": str(answer.get("stamp") or ""), "as_of": epoch_of(answer.get("as_of")), "offline_note": True}


def pinned_of(answer: dict[str, Any], base: str) -> WidgetData:
    """The pinned notes in nexnotes' order (newest change first), each opening the note."""
    items = []
    for one in answer.get("pinned") or []:
        if not isinstance(one, dict) or not one.get("id"):
            continue
        row: dict[str, Any] = {
            "id": str(one["id"]),
            # A note's own title, never put through the table of translations; the screen names an untitled one.
            "title": str(one.get("title") or "").strip(),
            "subtitle": str(one.get("first_line") or ""),
            "url": str(one.get("link") or "") or base,
        }
        progress = _progress(one.get("tasks"))
        if progress:
            row["done"], row["total"] = progress
        if one.get("owner"):
            row["owner"] = str(one["owner"])
        items.append(row)
    return WidgetData(
        status="ok",
        items=items,
        link=str(answer.get("link") or "") or base,
        meta={**_held(answer), "mode": "pinned", "more": count_of(answer.get("more")), "empty": "No note is pinned."},
    )


def note_of(note: dict[str, Any], writes: bool, limit: int, show_checked: bool, base: str) -> WidgetData:
    """One note: its checklist with the open items first, in the note's order, or its first lines.

    An item can be ticked here only with a token that writes and a note the account may write; ``check_note`` says
    why not, once, instead of boxes that answer with a refusal.
    """
    can = writes and note.get("can_check") is True
    note_id = str(note.get("id") or "")
    every = [one for one in note.get("items") or [] if isinstance(one, dict) and isinstance(one.get("index"), int)]
    open_items = [one for one in every if one.get("checked") is not True]
    ticked = [one for one in every if one.get("checked") is True]
    shown_from = open_items + (ticked if show_checked else [])
    shown = shown_from[:limit]
    items = []
    for one in shown:
        checked = one.get("checked") is True
        text = str(one.get("text") or "")
        row: dict[str, Any] = {
            "id": str(one["index"]),
            "title": text,
            "checked": checked,
            "depth": min(4, count_of(one.get("depth"))),
        }
        if can and note_id:
            row["actions"] = [Action(id="check", label="Open again" if checked else "Tick off", icon="check",
                                     params={"note": note_id, "index": one["index"], "text": text, "checked": not checked})]
        items.append(row)
    progress = _progress(note.get("tasks"))
    done, total = progress if progress else (len(ticked), len(every)) if every else (0, 0)
    reason = ""
    if every and not can:
        reason = ("This note is shared with you to read only." if writes
                  else "Read only: ticking off needs an API token with Read and write.")
    meta: dict[str, Any] = {
        **_held(note),
        "mode": "note",
        "title": str(note.get("title") or "").strip(),
        "more": len(shown_from) - len(shown) + count_of(note.get("more_items")),
        "lines": [str(line) for line in note.get("lines") or [] if str(line).strip()][:limit] if not every else [],
        "empty": "Everything is ticked off." if every else "This note is empty.",
        "actions_visible": True,
    }
    if total:
        meta["done"], meta["total"] = done, total
    if reason:
        meta["check_note"] = reason
    return WidgetData(
        status="ok",
        primary={"label": "Open", "value": len(open_items)} if every else None,
        items=items,
        link=str(note.get("link") or "") or base,
        meta=meta,
    )


ADAPTER = NexnotesAdapter()
