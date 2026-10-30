"""The card editor asks the provider of the assistant for a card (KARTEN-17).

Administrators only, like the editor itself. One request per administrator at a time, and it can be cancelled. The
provider is the one of "Ask nexdeck"; with none set up, or after it is taken away, every call answers ``assistant_off``.
What leaves for the provider is decided in :mod:`..cards.ai`, nowhere else.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import select

from ..adapters.base import AdapterError
from ..cards import ai, card_reads, credentials, demo, load, schema
from ..cards.load import Problem
from ..db import db_session
from ..deps import AdminUser, DbSession, error
from ..models import Integration
from ..services import chronicle
from ..services.assistant import settings
from .cards import _ask, _connection, _connection_number, _failed

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger("nexdeck.cards")

#: Code of the answer to a request that was cancelled, and the HTTP answer of each code of :class:`ai.AiError`.
CANCELLED = "ai_cancelled"
_HTTP = {"assistant_off": 409, "ai_busy": 409, CANCELLED: 409, "bad_request": 400}
#: Failures that say a path is wrong for the service. A service that is down or turns the connection away says nothing
#: about the card, so those are no problem of the proposal.
_PATH_FAILURES = frozenset({"http_error", "not_json", "redirected", "answer_too_large", "command_refused", "bad_path", "bad_param"})


class AiBody(BaseModel):
    mode: str = Field(max_length=12)
    description: str = Field(default="", max_length=2000)
    yaml: str = Field(default="", max_length=schema.MAX_DEFINITION * 2)
    kind: Annotated[str, StringConstraints(pattern=r"^(custom:)?[a-z0-9][a-z0-9_-]{0,59}$")] | None = None
    connection_id: int | None = None
    path: str | None = Field(default=None, max_length=500)
    include_values: bool = False


def _refused(failure: ai.AiError) -> HTTPException:
    return error(failure.code, failure.message, _HTTP.get(failure.code, status.HTTP_502_BAD_GATEWAY))


def _check(body: AiBody) -> schema.Request | None:
    """The request the answer is asked for, or ``None`` when no connection is named; refuses what cannot be asked."""
    if body.mode not in ai.MODES:
        raise error("bad_request", "Say whether to write a new card, change one or translate one.", status.HTTP_400_BAD_REQUEST)
    if body.mode == "new" and (body.connection_id is None or not body.path):
        raise error("bad_request", "A new card needs the connection and the path it reads.", status.HTTP_400_BAD_REQUEST)
    if body.mode != "new" and not body.yaml.strip():
        raise error("bad_request", "Give the text of the card.", status.HTTP_400_BAD_REQUEST)
    _connection_number(body.connection_id)
    if body.connection_id is None or not body.path:
        return None
    try:
        request = schema.Request(id="probe", path=body.path)
    except ValidationError:
        raise error("bad_path", "The path must start with a single / and name no host; it is always underneath the connection's address.", status.HTTP_400_BAD_REQUEST) from None
    # ⚠️ As in a probe: a secret in the path is refused before anything is asked or written down.
    if next(credentials.find(body.path), None) is not None:
        raise error("card_secret_value", "This looks like a key. A card holds no secrets: the connection sends its own.", status.HTTP_400_BAD_REQUEST)
    return request


async def _asked(body: AiBody, request: schema.Request | None, userid: int, username: str) -> tuple[str, Any]:
    """The kind of the connection and what the service answered at the path, asked the way the editor's probe asks."""
    if request is None:
        return body.kind or "", ai.MISSING
    assert body.connection_id is not None
    adapter, config, ctx = await _connection(body.connection_id)
    try:
        answer = await _ask(adapter, config, ctx, request)
    except AdapterError as failure:
        note_asked(userid, username, body.connection_id, [(request.path, failure.code)], "card help")
        raise
    note_asked(userid, username, body.connection_id, [(request.path, None)], "card help")
    return adapter.kind, answer


def note_asked(userid: int, username: str, number: int, asked: list[tuple[str, str | None]], how: str) -> None:
    """A line in the chronicle and the log for every question the card help put to a service, also one that failed.

    ``asked`` are the paths with the code of their failure, ``None`` for an answer. ⚠️ A question that failed was asked all
    the same, with the connection's credentials, like a probe that failed: the line says why, never what came back. The chat's
    draft wrote none, and the editor none when its first question failed (found in a real run on 1.0.1).
    """
    if not asked:
        return
    failed = [code for _path, code in asked if code]
    detail = ", ".join(f"[{code}] {path}" if code else path for path, code in asked)
    with db_session() as db:
        row = db.get(Integration, number)
        chronicle.record("card_probe", level="warn" if failed else "info", user_id=userid, integration_id=number if row else None,
                         name=row.name if row else "", detail=f"{detail} ({how})", db=db)
        db.commit()
    logger.info("%s had the card help ask %s at %s (%s)%s.", username, number, detail, how, f": {', '.join(failed)}" if failed else "")


def _tried_with(preferred: int | None, kinds: list[str]) -> tuple[int, dict[str, str] | None] | None:
    """The connection a proposal is asked through, and ``{"name", "kind"}`` of it when it is not the chosen one.

    The one chosen in the editor (in the chat the one the draft is for) when the card names its kind; only when the card names
    another kind the first real one of such a kind ("Ask AI" on an empty card). The administrator is told which one that was.
    """
    with db_session() as db:
        chosen = db.get(Integration, preferred) if preferred is not None else None
        if chosen is not None and chosen.kind in kinds:
            return chosen.id, None
        found = select(Integration).where(Integration.kind.in_(kinds), Integration.enabled.is_(True), Integration.demo.is_(False))
        other = db.scalar(found.order_by(Integration.id).limit(1))
        return (other.id, {"name": other.name, "kind": other.kind}) if other is not None else None


class _Verifier:
    """Asks the service the requests of a proposal, the way the editor's preview will (found in a real run on 1.0.0).

    The provider guessed paths from a lookalike service (Sonarr's for nexcrate), and the card failed only once taken over.
    Nothing of the answers goes to the provider, only which path failed and nexdeck's own sentence for it, and the shape of an
    answer it has not seen, never its values (:func:`ai._shapes`). Without a real connection of the kind, in demo mode, or with
    the service down, nothing can be said and nothing is held against the card. The answers of the last card asked stay in
    ``answers`` (request id -> answer) for its examples.

    ⚠️ Only paths the administrator named (``named``: the path he asked about, the paths of the card in the editor) or that
    nexdeck's own cards of the kind read (:func:`card_reads.read_by_own_cards`). A GET is not always a read: ``/v1/update``
    starts an update run of Watchtower, and the provider's proposal (or an instruction in the text of a shop card) would have
    sent it before the administrator saw anything (B1 of a review of 1.0.2). Any other path is left for the preview with real
    data after he takes the card over (``unasked``).
    """

    def __init__(self, preferred: int | None, userid: int, username: str, named: frozenset[str] = frozenset()) -> None:
        self.preferred, self.userid, self.username, self.named = preferred, userid, username, named
        self.answers: dict[str, Any] = {}

    async def __call__(self, definition: Any) -> ai.Checked:
        self.answers = {}
        preferred, userid, username = self.preferred, self.userid, self.username
        tried = _tried_with(preferred, list(definition.requires))
        if tried is None:
            return ai.Checked([])
        number, other = tried
        try:
            adapter, config, ctx = await _connection(number, list(definition.requires))
        except AdapterError:
            return ai.Checked([])
        problems: list[Problem] = []
        asked: list[tuple[str, str | None]] = []
        unasked: list[str] = []
        for index, request in enumerate(definition.requests):
            if "{" in request.path:
                continue  # a name the administrator fills in later: nothing to ask yet, and not the provider's to guess
            if request.path not in self.named and not card_reads.read_by_own_cards(adapter.kind, request.path):
                unasked.append(request.path)
                continue
            try:
                self.answers[request.id] = await _ask(adapter, config, ctx, request)
                asked.append((request.path, None))
            except AdapterError as failure:
                asked.append((request.path, failure.code))
                if failure.code in _PATH_FAILURES:
                    problems.append(Problem(
                        ai.PATH_FAILED, f"The service did not answer {request.path}: {failure.message}", path=f"requests[{index}].path",
                        params={"path": request.path, "failure": failure.code},
                    ))
        note_asked(userid, username, number, asked, "card help, check")
        return ai.Checked(problems, dict(self.answers), other if asked else None, unasked)


def _verifier(preferred: int | None, userid: int, username: str, named: frozenset[str] = frozenset()) -> _Verifier:
    return _Verifier(preferred, userid, username, named)


def named_paths(body: AiBody) -> frozenset[str]:
    """The paths the administrator named: the one he asks about, and those of the card he has in the editor."""
    found = {body.path} if body.path else set()
    try:
        found |= {request.path for request in load.load_definition(body.yaml).definition.requests}
    except load.CardInvalid:
        pass  # a card with problems names no paths that count
    return frozenset(found)


def with_examples(outcome: ai.Outcome, answers: dict[str, Any]) -> None:
    """A proposal without examples gets the service's answers, made up the way a card's demo data is (they stay in nexdeck).

    The preview beside a proposal draws from examples, and the provider writes none: without them it could not be drawn
    (found in a real run on 1.0.0). A card that has examples keeps its own.
    """
    if not outcome.ok or outcome.definition is None or outcome.definition.demo or not answers:
        return
    try:
        made, _cut = demo.disguise(answers)
        text = ai.with_demo(outcome.yaml, made)
        loaded = load.load_definition(text)
    except (AdapterError, load.CardInvalid):
        return
    outcome.yaml, outcome.definition = text, loaded.definition


@router.post("/ai", summary="Have the provider of the assistant write, change or translate a card")
async def card_with_ai(body: AiBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    if not settings.ready(db):
        raise error("assistant_off", "The assistant is not set up.", status.HTTP_409_CONFLICT)
    request = _check(body)
    config, key = settings.stored(db), settings.key_of(db)
    userid, username = user.id, user.username
    db.rollback()  # the provider may take minutes; a read transaction should not wait with it

    async def work() -> ai.Outcome:
        kind, answer = await _asked(body, request, userid, username)
        verify = _verifier(body.connection_id, userid, username, named_paths(body) if body.mode != "translate" else frozenset())
        outcome = await ai.generate(
            ai.Ask(mode=body.mode, description=body.description, yaml=body.yaml, connection_kind=kind, path=body.path or "", answer=answer, include_values=body.include_values),
            config, key, verify,
        )
        with_examples(outcome, verify.answers)
        return outcome

    try:
        finished, outcome = await ai.supervised(userid, work())
    except ai.Busy:
        raise error("ai_busy", "A card is being written already. Wait for it or cancel it.", status.HTTP_409_CONFLICT) from None
    except AdapterError as failure:
        raise _failed(failure) from failure
    except ai.AiError as failure:
        raise _refused(failure) from None
    if not finished:
        with db_session() as fresh:
            gone = not settings.ready(fresh)
        raise _refused(ai.AiError("assistant_off", "The assistant was switched off.") if gone else ai.AiError(CANCELLED, "The request was cancelled."))
    logger.info("%s had a card %s by the assistant (%s).", username, "written" if outcome.ok else "tried", body.mode)
    return outcome.body()


@router.delete("/ai", summary="Cancel the card being written for you")
def cancel(user: AdminUser) -> dict[str, bool]:
    return {"cancelled": ai.cancel(user.id)}
