"""Custom cards: list them, keep them, copy them, delete them, say who may place them (KARTEN-11).

Everything here is for administrators, except the library list, which tells every member what he may put on a board.
A card is kept as the text its author wrote (``cards/store.py``); this router only decides who may touch it and writes
it down in the log.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import get_adapter
from ..adapters.base import AdapterError, Context, shape_for_display
from ..adapters.custom import ADAPTER as CUSTOM
from ..adapters.custom import present
from ..adapters.defined import MissingAdapter
from ..cards import card_reads, credentials, exchange, load, pipeline, probe, schema, source, store
from ..cards import demo as card_demo
from ..config import get_settings
from ..db import db_session
from ..deps import AdminUser, DbSession, MemberUser, error
from ..models import Board, CardRecord, Integration, Page, Role, User, Widget
from ..services import chronicle
from ..services.collector import collector, demo_flag
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger("nexdeck.cards")


class CardText(BaseModel):
    """The text of a card, word for word as it is edited."""

    yaml: str = Field(max_length=schema.MAX_DEFINITION * 2)


class ReplaceBody(CardText):
    """The new text, and what the editor read when it opened the card (KARTEN-9 EC-3)."""

    base: str | None = Field(default=None, max_length=64, description="The updated_at that was read; a different one means somebody saved meanwhile.")
    overwrite: bool = Field(default=False, description="Save over what somebody saved meanwhile.")


class ImportCheckBody(BaseModel):
    """The text of a file as it was read or pasted; the size is checked in :mod:`..cards.exchange`, which says why it refuses."""

    text: str = Field(max_length=4_000_000)


class ImportBody(ImportCheckBody):
    """What to do with each document whose name is taken: ``card:<slug>`` or ``integration:<short>`` to replace, copy or skip."""

    choices: dict[str, str] = Field(default_factory=dict, max_length=exchange.MAX_DOCUMENTS)


class ProbeBody(BaseModel):
    integration_id: int
    path: str = Field(min_length=1, max_length=500)


class PreviewBody(CardText):
    integration_id: int | None = None
    demo: bool = False


class DemoBody(CardText):
    integration_id: int


class SharingBody(BaseModel):
    allowed: bool


#: The most a connection's number can be: what the database holds as an integer and then some, so no number is a failure.
MAX_INTEGRATION = 2**31 - 1


def _connection_number(number: int | None) -> None:
    """A number no connection has is a mistake of the caller, not of the server (found in the review of KARTEN-9, 25.10.2026)."""
    if number is not None and not 1 <= number <= MAX_INTEGRATION:
        raise error("bad_integration", "That is not the number of a connection.", status.HTTP_400_BAD_REQUEST)


def _invalid(failure: load.CardInvalid) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "card_invalid", "message": str(failure), **failure.detail()})


def _too_many() -> HTTPException:
    return error("too_many_cards", f"There are {store.MAX_CARDS} custom cards already, which is the most nexdeck keeps. Delete one first.", status.HTTP_409_CONFLICT)


def _row(db: Session, slug: str) -> CardRecord:
    row = db.scalar(select(CardRecord).where(CardRecord.slug == slug, CardRecord.kind == "card"))
    if row is None:
        raise error("not_found", "There is no such card.", status.HTTP_404_NOT_FOUND)
    return row


def _requirement(kind: str) -> dict[str, str]:
    """A kind of connection as people read it: its name and its logo."""
    if kind.startswith("custom:"):
        return {"kind": kind, "label": kind.partition(":")[2], "icon": ""}
    try:
        adapter = get_adapter(kind)
    except KeyError:
        return {"kind": kind, "label": kind, "icon": ""}
    return {"kind": kind, "label": adapter.label, "icon": adapter.icon}


def _placed(db: Session) -> dict[str, dict[int, tuple[str, str]]]:
    """Where each card stands: the boards that hold a widget of it, by the short name in the widget's options."""
    found: dict[str, dict[int, tuple[str, str]]] = {}
    query = (
        select(Widget.options, Board.id, Board.name, Board.slug)
        .join(Page, Page.id == Widget.page_id)
        .join(Board, Board.id == Page.board_id)
        .where(Widget.kind.like("custom.%"))
    )
    for options, board_id, board_name, board_slug in db.execute(query):
        slug = str((options or {}).get("card") or "")
        if slug:
            found.setdefault(slug, {})[board_id] = (board_slug, board_name)
    return found


def _view(row: CardRecord, placed: dict[str, dict[int, tuple[str, str]]]) -> dict[str, Any]:
    data = row.definition or {}
    boards = placed.get(row.slug, {})
    requires = [str(kind) for kind in data.get("requires", [])]
    return {
        "slug": row.slug,
        "name": data.get("name", row.slug),
        "description": data.get("description"),
        "form": data.get("form", ""),
        "version": data.get("version", ""),
        "author": data.get("author"),
        "requires": [_requirement(kind) for kind in requires],
        "origin": row.origin,
        "shop_version": row.shop_version,
        "boards": [{"id": number, "slug": at, "name": name} for number, (at, name) in sorted(boards.items(), key=lambda one: one[1][1].lower())],
        "users_may_place": row.users_may_place,
        "updated_at": row.updated_at,
    }


def _tell(db: Session, slug: str) -> None:
    """Every card of this definition fetches itself again and every open board hears it: a change shows at once (KARTEN-11)."""
    widgets = [w for w in db.scalars(select(Widget).where(Widget.kind.like("custom.%"))) if str((w.options or {}).get("card") or "") == slug]
    boards: set[int] = set()
    for widget in widgets:
        page = db.get(Page, widget.page_id)
        if page is not None:
            boards.add(page.board_id)
        collector.schedule(widget.id)
    for board_id in boards:
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


# -- what the editor and the shop read -----------------------------------------------------


@router.get("/sources", summary="The kinds of connection a custom card can read through")
def sources(user: AdminUser) -> list[dict[str, Any]]:
    return source.sources()


@router.get("/sources/{kind}/reads", summary="What nexdeck can ask of a kind of service, as its built-in cards do")
def source_reads(kind: str, user: AdminUser) -> dict[str, Any]:
    """The GET requests the built-in cards of this kind make, found in the code (:mod:`..cards.card_reads`).

    ⚠️ By kind, not by connection: a service with no card on any board, or no connection at all, has the same list.
    Nothing that proves who asks is in a path, and nothing is asked of the service here.
    """
    try:
        adapter = get_adapter(kind)
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_such_kind", "message": f"There is no kind {kind!r}.", "hint": ""}) from error
    if not adapter.raw_access:
        raise _failed(AdapterError(f"{adapter.label} cannot be read by a custom card.", code="no_raw_access"))
    if adapter.custom:
        # An own connection says itself what is worth asking (KARTEN-3): its own list, with the labels its author wrote.
        return {"reads": [{"path": one.path, "label": one.label, "widgets": []} for one in adapter.definition.reads]}  # type: ignore[attr-defined]
    labels = {one.kind: one.label for one in adapter.widgets}
    return {"reads": [
        {"path": one["path"], "widgets": [{"kind": name, "label": labels[name]} for name in one["widgets"] if name in labels]}
        for one in card_reads.reads_of(kind)
    ]}


@router.get("/schema", summary="The JSON schema of a custom card")
def json_schema(user: AdminUser) -> dict[str, Any]:
    return schema.json_schema()


# -- what the editor asks (KARTEN-9) -----------------------------------------------------

#: Seconds a request to a service may take before the editor is told it did not answer.
ASK_SECONDS = 20
#: Failures that are the card's or the caller's doing, not the service's.
_ASKED_WRONG = frozenset({"bad_path", "bad_param", "kind_mismatch", "no_raw_access", "read_only", "command_refused", "no_demo_data", "demo_too_large", "too_slow", "form_changed", "card_secret_value"})
#: The code of an editor call that is not made because the installation or the connection shows invented data.
DEMO_MODE = "demo_mode"


def _failed(failure: AdapterError) -> HTTPException:
    """A failure of the service or of the card as an answer, the way the card itself says it: code, message and what to do.

    ⚠️ Never 401 or 403, whatever the service said: the editor reads those as the end of its own session.
    """
    if failure.code in _ASKED_WRONG:
        http = status.HTTP_400_BAD_REQUEST
    elif failure.code == DEMO_MODE:
        http = status.HTTP_409_CONFLICT
    elif failure.code == "no_integration":
        http = status.HTTP_404_NOT_FOUND
    else:
        http = status.HTTP_502_BAD_GATEWAY
    return HTTPException(http, {"code": failure.code, "message": failure.message, "hint": failure.hint})


def _demo_mode(integration_id: int | None) -> AdapterError | None:
    """Why the real service must not be asked: demo mode of the installation or of the connection, as the board holds to it.

    ⚠️ A card on a board shows invented data then, so a probe or an example taken from the real service would not be what
    the card shows. The editor is told in words, with the place where demo mode is switched off (found in the review of KARTEN-9, 25.10.2026).
    """
    if get_settings().demo:
        return AdapterError(
            "Demo mode is on for the whole installation through NEXDECK_DEMO, so the real service is not asked.", code=DEMO_MODE,
            hint="Remove the variable NEXDECK_DEMO from the container and restart it. Until then a card shows invented data.",
        )
    if demo_flag():
        return AdapterError(
            "Demo mode is on for the whole installation, so the real service is not asked.", code=DEMO_MODE,
            hint="Switch it off under System > Integrations. Until then a card shows invented data.",
        )
    if integration_id is not None:
        with db_session() as db:
            one = db.get(Integration, integration_id)
            if one is not None and one.demo:
                return AdapterError(
                    f"The connection {one.name} is in demo mode, so the real service is not asked.", code=DEMO_MODE,
                    hint="Switch off demo mode of the connection under System > Integrations. Until then a card on it shows invented data.",
                )
    return None


async def _connection(integration_id: int, kinds: list[str] | None = None) -> tuple[Any, dict[str, Any], Context]:
    """The connection a probe, a preview or an example is fetched through: a kind a card may read through, and one the card names."""
    from ..services.collector import collector

    in_demo = _demo_mode(integration_id)
    if in_demo is not None:
        raise in_demo
    adapter, config, ctx = await collector.resolve_integration(integration_id)
    if isinstance(adapter, MissingAdapter):
        await adapter.test(config, ctx)  # says "integration missing" in its own words (KARTEN-3 EC-6)
    if not adapter.raw_access:
        raise AdapterError(f"{adapter.label} cannot be read by a custom card.", code="no_raw_access", hint="Pick a connection of another kind.")
    if kinds is not None and adapter.kind not in kinds:
        raise AdapterError(
            f"This card does not read through a {adapter.label} connection.", code="kind_mismatch", hint="Pick a connection of a kind the card names."
        )
    return adapter, config, ctx


async def _ask(adapter: Any, config: dict[str, Any], ctx: Context, request: schema.Request) -> Any:
    try:
        return await asyncio.wait_for(source.fetch_source(adapter, config, ctx, request), ASK_SECONDS)
    except TimeoutError:
        raise AdapterError("The service did not answer in time.", code="unreachable", hint="Check the URL and the network.") from None


async def _answers(definition: Any, integration_id: int) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Every request of a definition asked of the connection, in the order they are written."""
    adapter, config, ctx = await _connection(integration_id, list(definition.requires))
    return {request.id: await _ask(adapter, config, ctx, request) for request in definition.requests}, adapter, config


def _definition(text: str) -> Any:
    try:
        return load.load_definition(text).definition
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure


@router.post("/probe", summary="Ask a connection one path and show the answer as a tree")
async def probe_path(body: ProbeBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The raw answer of a service goes to the administrator who asked and nowhere else; the chronicle keeps the question, never the answer (KARTEN-9 EC-4)."""
    try:
        request = schema.Request(id="probe", path=body.path)
    except ValidationError:
        raise _failed(AdapterError(
            "The path must start with a single / and name no host; it is always underneath the connection's address.", code="bad_path",
            hint="Write the path of the request, such as /api/v3/queue.",
        )) from None
    # ⚠️ A secret in the path is refused as in a card, before anything is asked, kept or written down: the path goes into
    # the chronicle and the log, and those end up in extracts and backups (found in the review of KARTEN-9, 25.10.2026).
    _connection_number(body.integration_id)
    secret = next(credentials.find(body.path), None)
    if secret is not None:
        raise _failed(AdapterError(
            f"This looks like {credentials.PHRASES[secret.what]}. A card holds no secrets: the connection keeps them and adds them to the request.",
            code="card_secret_value", hint="Leave the key out of the path; the connection sends its own.",
        ))
    name = db.scalar(select(Integration.name).where(Integration.id == body.integration_id)) or ""
    try:
        adapter, config, ctx = await _connection(body.integration_id)
        answer = await _ask(adapter, config, ctx, request)
    except AdapterError as failure:
        if failure.code == DEMO_MODE:
            raise _failed(failure) from failure  # nothing was asked, so there is nothing to write down
        # A probe that failed was asked all the same, with the connection's credentials: the line says why, never what came back.
        logger.info("%s probed %s at %s: %s.", user.username, name or body.integration_id, body.path, failure.code)
        chronicle.record("card_probe", level="warn", user_id=user.id, integration_id=body.integration_id if name else None, name=name,
                         detail=f"[{failure.code}] {body.path}", db=db)
        db.commit()
        raise _failed(failure) from failure
    tree = await asyncio.to_thread(probe.build, answer)
    logger.info("%s probed %s at %s.", user.username, name or body.integration_id, body.path)
    chronicle.record("card_probe", user_id=user.id, integration_id=body.integration_id, name=name, detail=body.path, db=db)
    db.commit()
    return tree


def _with_preview_pictures(data: dict[str, Any], integration_id: int | None) -> dict[str, Any]:
    """The pictures of a preview come through the administrator's own route, since no widget stands behind them."""
    if integration_id is None:
        return data

    def route(art: str) -> str:
        return f"/api/v1/cards/preview-image?integration_id={integration_id}&path={quote(art[6:], safe='')}"

    for item in data.get("items") or []:
        art = item.get("art")
        if isinstance(art, str) and art.startswith("proxy:"):
            item["art"] = route(art)
    # The pictures of a card of blocks stand in its tree, at any depth (KARTEN-7).
    pending = [data.get("meta", {}).get("blocks") or []]
    while pending:
        for block in pending.pop():
            if not isinstance(block, dict):
                continue
            if isinstance(block.get("src"), str) and block["src"].startswith("proxy:"):
                block["src"] = route(block["src"])
            pending.append(block.get("children") or [])
            for row in block.get("rows") or []:
                pending.append(row.get("blocks") or [])
    return data


@router.post("/preview", summary="Work out what a card text shows, with the answers of a connection or with its demo data")
async def preview(body: PreviewBody, user: AdminUser) -> dict[str, Any]:
    """The same values, in the same shape, as the card has on a board: ``adapters/custom.present`` and the passes every card goes through."""
    _connection_number(body.integration_id)
    definition = _definition(body.yaml)
    # In demo mode the card shows its demo data on a board, and so it does here: nothing is asked of the service.
    # Live data was asked for, and demo mode answers instead: the editor says so beside its switch.
    forced = not body.demo and body.integration_id is not None and _demo_mode(body.integration_id) is not None
    demo = body.demo or body.integration_id is None or forced
    base = ""
    try:
        if demo:
            answers = pipeline.demo_answers(definition)
            if answers is None:
                raise AdapterError(
                    "No demo data. The card has no example answers.", code="no_demo_data",
                    hint="Write example answers, or take them over from a probe.",
                )
        else:
            assert body.integration_id is not None
            answers, adapter, config = await _answers(definition, body.integration_id)
            base = adapter.raw_base(config)
        # ⚠️ In a thread of its own, like the card on a board: a filter over a large answer cannot be interrupted.
        result = await asyncio.to_thread(pipeline.run, definition, answers)
    except AdapterError as failure:
        raise _failed(failure) from failure
    data = present(definition, result, base=base, pictures=not demo)
    data = shape_for_display(data, CUSTOM, definition.form, {})
    out = _with_preview_pictures(data.model_dump(), None if demo else body.integration_id)
    if forced:
        out["meta"] = {**(out.get("meta") or {}), "demo_mode": True}
    return out


@router.post("/demo", summary="Example answers made from the real ones of a connection: shortened and made up")
async def make_demo(body: DemoBody, user: AdminUser) -> dict[str, Any]:
    """The editor shows the result before it is taken over and lets the author change single values (KARTEN-9 AC-10)."""
    _connection_number(body.integration_id)
    definition = _definition(body.yaml)
    try:
        answers, _adapter, _config = await _answers(definition, body.integration_id)
        made, cut = await asyncio.to_thread(card_demo.disguise, answers)
    except AdapterError as failure:
        raise _failed(failure) from failure
    return {"demo": made, "cut": cut}


@router.post("/check", summary="Say whether a card text is good, and what is wrong with it if not")
def check(body: CardText, user: AdminUser) -> dict[str, Any]:
    """The problems carry their line, so the YAML view can mark it (KARTEN-10)."""
    try:
        load.load_definition(body.yaml)
    except load.CardInvalid as failure:
        return {"ok": False, "problems": [problem.as_dict() for problem in failure.problems]}
    return {"ok": True}


@router.get("/preview-image", summary="A picture of a preview, through the connection the preview reads from")
async def preview_image(integration_id: int, path: str, user: AdminUser) -> Response:
    """What ``/widgets/{id}/image`` is for a card on a board, for a card that stands on no board yet.

    ⚠️ The same rule as there, no looser: only a path or an address this server itself read out of the answers of a card
    and signed (for this connection, in the first case) is fetched, and a path on the connection goes out with the
    connection's credentials. The signature is what keeps an administrator's session from being a way to fetch any path.
    """
    from ..services.collector import collector
    from .widgets import bad_picture_path, cached_image, custom_picture, serve_image

    _connection_number(integration_id)
    in_demo = _demo_mode(integration_id)
    if in_demo is not None:
        raise _failed(in_demo)
    refused = bad_picture_path(path)
    if refused is not None:
        raise refused
    # ⚠️ Minus the number: a widget's pictures are kept under its own (positive) number and must never be answered for a preview.
    key = (-integration_id, path)
    kept = cached_image(key)
    if kept is not None:
        return kept

    async def service() -> tuple[Any, dict[str, Any], Context]:
        try:
            return await collector.resolve_integration(integration_id)
        except AdapterError as failure:
            raise error("not_found", str(failure), status.HTTP_404_NOT_FOUND) from failure

    where, client, own = await custom_picture(path, service)
    return await serve_image(client, where, key, own=own)


# -- the library -----------------------------------------------------------------------


@router.get("/library", summary="The custom cards this account may put on a board, with the connections that fit")
def library(user: MemberUser, db: DbSession) -> dict[str, Any]:
    """Administrators see every card; anybody else only the ones released for users, and never a connection reserved for administrators (KARTEN-11 AC-2 to AC-4).

    ⚠️ ``fits`` is what the card could be placed on right now. A card with no fitting connection is still listed, so the
    library can offer to add the integration (AC-12).
    """
    admin = user.role == Role.admin.value
    connections = [
        one for one in db.scalars(select(Integration).order_by(Integration.name)) if (admin or not one.admin_only)
    ]
    out: list[dict[str, Any]] = []
    for row in store.listing(db):
        if not (admin or row.users_may_place):
            continue
        view = _view(row, {})
        needed = {entry["kind"] for entry in view["requires"]}
        fits = []
        for one in connections:
            if one.kind not in needed:
                continue
            try:
                if not get_adapter(one.kind).raw_access:
                    continue
            except KeyError:
                continue
            fits.append({"id": one.id, "name": one.name, "kind": one.kind})
        # ``main`` is the value a card of blocks names as its main one: only with it is the card a tile of key figures (KARTEN-7 AC-8).
        out.append({k: view[k] for k in ("slug", "name", "description", "form", "requires", "version")} | {"fits": fits, "main": (row.definition or {}).get("main")})
    return {"cards": out}


# -- the list --------------------------------------------------------------------------


@router.get("", summary="List the custom cards")
def list_cards(user: AdminUser, db: DbSession) -> dict[str, Any]:
    from ..workshop import catalog as shop_catalog
    from ..workshop import state as shop_state
    from ..workshop import updates as shop_updates

    placed = _placed(db)
    rows = store.listing(db)
    # What the Card shop has to say about the cards from it (KARTEN-15 AC-1, AC-6); nothing while the shop is off (EC-3).
    on = shop_state.enabled(db)
    hints = shop_updates.card_hints(db, shop_catalog.known(shop_state.repo(db)) if on else None)
    return {"cards": [{**_view(row, placed), "shop": hints.get(row.slug)} for row in rows], "limit": store.MAX_CARDS}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save a new custom card from its text")
def create_card(body: CardText, user: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        row = store.create(db, body.yaml, user_id=user.id)
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure
    except store.TooManyCards:
        raise _too_many() from None
    logger.info("Custom card %r created by %s.", row.slug, user.username)
    chronicle.record("card_definition_added", user_id=user.id, name=row.slug, detail="made", db=db)
    db.commit()
    return _view(row, {})


def _refused(failure: exchange.Refused) -> HTTPException:
    return HTTPException(failure.status, {"code": failure.code, "message": failure.message, **failure.more})


@router.post("/import/check", summary="Read a file of cards and own connections and say what is in it, without making anything")
def import_check(body: ImportCheckBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Per document its name, what it reads through, its buttons and the problems with their line in the file (KARTEN-12 AC-2).

    A file pasted as text and a file read from disk come the same way (EC-7). Whether the file is too large, has too many
    documents or is empty answers 400 with the reason (EC-1); a document that is wrong is a document with problems.
    """
    try:
        return exchange.inspect(db, body.text).view()
    except exchange.Refused as failure:
        raise _refused(failure) from failure


@router.post("/import", status_code=status.HTTP_201_CREATED, summary="Make the cards and own connections of a file, all of them or none")
def import_cards(body: ImportBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """A name that is taken needs a choice (replace, copy or skip); without it nothing is made (KARTEN-12 AC-3, EC-5)."""
    from ..cards import integration_store

    with store.saving, integration_store.saving:
        try:
            outcome = exchange.run(db, body.text, body.choices, user_id=user.id)
            db.commit()
        except exchange.Refused as failure:
            db.rollback()
            raise _refused(failure) from failure
        except BaseException:
            db.rollback()
            raise
    exchange.finish(outcome)
    logger.info("File imported by %s: %s.", user.username, outcome.view())
    return outcome.view()


@router.get("/{slug}/export", summary="A custom card as a file, with the own connections it needs")
def export_card(slug: str, user: AdminUser, db: DbSession) -> Response:
    """The text of the card as it was saved, then of each own connection it names that exists here (KARTEN-12 AC-1, AC-4)."""
    row = _row(db, slug)
    logger.info("Custom card %r exported by %s.", slug, user.username)
    return Response(
        content=exchange.join(exchange.card_documents(db, row)), media_type=exchange.MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{exchange.file_name(slug)}"'},
    )


@router.get("/{slug}", summary="Read a custom card with its text")
def read_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    row = _row(db, slug)
    return {**_view(row, _placed(db)), "yaml": row.yaml_source}


def _moment(text: str) -> datetime:
    try:
        found = datetime.fromisoformat(text)
    except ValueError:
        raise error("bad_base", "The time the card was read at is not a time.") from None
    return found.astimezone(UTC) if found.tzinfo else found.replace(tzinfo=UTC)


def _changed_meanwhile(db: Session, row: CardRecord) -> HTTPException:
    """Who saved last, and when: what the editor tells the second administrator (KARTEN-9 EC-3)."""
    by = None
    for number in (row.updated_by, row.created_by):
        found = db.get(User, number) if number is not None else None
        if found is not None:
            by = found.username
            break
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {"code": "card_changed_meanwhile", "message": "This card was saved by somebody else while you had it open.", "by": by, "at": row.updated_at.isoformat().replace("+00:00", "Z")},
    )


@router.put("/{slug}", summary="Replace the text of a custom card; every board shows the change at once")
def replace_card(slug: str, body: ReplaceBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """With ``base``, a card that somebody saved since is not replaced unless ``overwrite`` says so (KARTEN-9 EC-3)."""
    with store.saving:
        row = db.scalar(select(CardRecord).where(CardRecord.slug == slug, CardRecord.kind == "card"))
        if row is None:
            # ⚠️ Somebody else deleted it while this one had it open (KARTEN-11 EC-6). The editor says so and offers "Save as new".
            raise error("card_deleted", "This card was deleted meanwhile.", status.HTTP_404_NOT_FOUND)
        if body.base is not None and not body.overwrite and _moment(body.base) != row.updated_at:
            raise _changed_meanwhile(db, row)
        try:
            store.update(db, row, body.yaml, user_id=user.id)
        except load.CardInvalid as failure:
            raise _invalid(failure) from failure
        logger.info("Custom card %r changed by %s.", slug, user.username)
        chronicle.record("card_definition_changed", user_id=user.id, name=slug, detail="text changed", db=db)
        db.commit()
    _tell(db, slug)
    return {**_view(row, _placed(db)), "yaml": row.yaml_source}


@router.delete("/{slug}", summary="Delete a custom card; the cards that show it say that the definition is missing")
def delete_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    row = _row(db, slug)
    boards = len(_placed(db).get(slug, {}))
    store.delete(db, row)
    logger.info("Custom card %r deleted by %s; it stood on %d board(s).", slug, user.username, boards)
    chronicle.record("card_definition_removed", user_id=user.id, name=slug, detail=f"it stood on {boards} board(s)", db=db)
    db.commit()
    _tell(db, slug)
    return {"boards": boards}


def _free_slug(db: Session, slug: str) -> str:
    taken = {one.slug for one in store.listing(db)} | set(store.RESERVED_SLUGS)
    for number in range(1, 1000):
        suffix = "-copy" if number == 1 else f"-copy-{number}"
        candidate = f"{slug[: 60 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise error("no_free_name", "No free short name for a copy.")


@router.post("/{slug}/copy", status_code=status.HTTP_201_CREATED, summary="Make a copy of a custom card under a new short name")
def copy_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The copy is a card of this installation (``local``), shared with nobody, whatever the original was (KARTEN-11 AC-5)."""
    row = _row(db, slug)
    new = _free_slug(db, slug)
    try:
        lines = load.load_definition(row.yaml_source).lines
        number = lines.get(("slug",))
        if number is None:
            raise error("card_unreadable", "The short name of this card could not be found in its text.")
        text = row.yaml_source.split("\n")
        text[number - 1] = re.sub(r"^(\s*slug\s*:\s*)([\"']?)[^\s#\"']+\2", lambda found: f"{found.group(1)}{new}", text[number - 1], count=1)
        copy = store.create(db, "\n".join(text), user_id=user.id)
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure
    except store.TooManyCards:
        raise _too_many() from None
    logger.info("Custom card %r copied to %r by %s.", slug, copy.slug, user.username)
    chronicle.record("card_definition_added", user_id=user.id, name=copy.slug, detail=f"copy of {slug}", db=db)
    db.commit()
    return _view(copy, {})


@router.put("/{slug}/users", summary="Say whether users may place a custom card, or only administrators")
def share_card(slug: str, body: SharingBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Taking it back leaves the cards that stand on boards where they are; only placing a new one is closed (KARTEN-11 EC-1)."""
    row = _row(db, slug)
    store.set_users_may_place(db, row, body.allowed)
    logger.info("Custom card %r %s for users by %s.", slug, "released" if body.allowed else "reserved for administrators", user.username)
    chronicle.record("card_definition_changed", user_id=user.id, name=slug,
                     detail="released for users" if body.allowed else "reserved for administrators", db=db)
    db.commit()
    return _view(row, _placed(db))
