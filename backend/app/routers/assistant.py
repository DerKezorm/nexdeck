"""The assistant ("Ask nexdeck"): its setting under System and the chat itself.

Administrators only, all of it. The assistant looks at every board and every
connection, and the provider's bill goes to whoever set it up.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..cards import ai as card_ai
from ..deps import AdminUser, DbSession, error
from ..models import Conversation
from ..services.assistant import chat, providers, settings

router = APIRouter(prefix="/api/v1", tags=["assistant"])
logger = logging.getLogger("nexdeck.assistant")

#: One answer at a time per person: a second click would pay twice for the same question.
_busy: set[int] = set()


class AssistantSetting(BaseModel):
    provider: str = Field(max_length=20)
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=120)
    #: Left out keeps the stored key, an empty one removes it.
    key: str | None = Field(default=None, max_length=500)


class ModelsAsked(BaseModel):
    provider: str = Field(max_length=20)
    base_url: str = Field(default="", max_length=500)
    key: str | None = Field(default=None, max_length=500)


class Question(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    #: Asked from the diagnosis page of this service (roadmap M6): the assistant starts there.
    about: str | None = Field(default=None, max_length=200)


class Grant(BaseModel):
    grant: str = Field(min_length=1, max_length=300)


def _refusal(failure: providers.AssistantError) -> Exception:
    code = {"not_found": status.HTTP_404_NOT_FOUND, "off": status.HTTP_409_CONFLICT}.get(failure.code, status.HTTP_502_BAD_GATEWAY)
    if failure.code in ("bad_grant", "no_list"):
        code = status.HTTP_400_BAD_REQUEST
    return error(failure.code, failure.message, code)


def _mine(db: DbSession, user_id: int, conversation_id: int) -> Conversation:
    found = db.get(Conversation, conversation_id)
    if found is None or found.user_id != user_id:
        raise error("not_found", "No such conversation.", status.HTTP_404_NOT_FOUND)
    return found


# -- the setting ---------------------------------------------------------------------------


@router.get("/settings/assistant", summary="Which provider the assistant uses")
def read_setting(user: AdminUser, db: DbSession) -> dict:
    return settings.public(db)


@router.put("/settings/assistant", summary="Choose the assistant's provider, model and key")
def write_setting(body: AssistantSetting, user: AdminUser, db: DbSession) -> dict:
    try:
        settings.store(db, provider=body.provider, base_url=body.base_url, model=body.model, key=body.key)
    except settings.Refused as refused:
        raise error(refused.code, refused.message) from None
    db.commit()
    value = settings.public(db)
    if not value["ready"]:
        card_ai.cancel_all()  # a card being written for the editor ends with the provider (KARTEN-17 EC-6)
    logger.info("The assistant uses %s (%s) from now on, set by %s.", value["provider"], value["model"] or "no model", user.username)
    return value


@router.post("/settings/assistant/test", summary="Ask the provider one short question")
async def test_setting(user: AdminUser, db: DbSession) -> dict:
    """Costs a few tokens on a paid provider; the interface says so next to the button."""
    if not settings.ready(db):
        raise error("off", "The assistant is not set up.", status.HTTP_409_CONFLICT)
    config, key = settings.stored(db), settings.key_of(db)
    db.rollback()
    try:
        turn = await providers.turn(config, key, "Answer with the single word OK.", [{"role": "user", "text": "Are you there?"}], [])
    except providers.AssistantError as failure:
        raise _refusal(failure) from None
    return {"ok": True, "model": config["model"], "answer": turn.text[:80]}


@router.post("/settings/assistant/models", summary="The models a service offers, with what is typed or stored")
async def list_models(body: ModelsAsked, user: AdminUser, db: DbSession) -> list[dict]:
    if body.provider == "openai" and not body.base_url.strip().startswith(("http://", "https://")):
        raise error("bad_address", "The address starts with http:// or https://.")
    key = settings.key_for(db, body.provider, body.base_url, body.key)
    db.rollback()
    if body.provider == "anthropic" and not key:
        raise error("missing_key", "Claude needs its API key.")
    try:
        return await providers.list_models(body.provider, body.base_url, key)
    except providers.AssistantError as failure:
        raise _refusal(failure) from None


@router.get("/assistant", summary="Whether the chat is there to be opened")
def assistant_state(user: AdminUser, db: DbSession) -> dict:
    value = settings.public(db)
    return {"ready": value["ready"], "provider": value["provider"], "model": value["model"],
            "leaves_the_house": value["leaves_the_house"], "keep_days": chat.KEEP_DAYS}


# -- the chat ------------------------------------------------------------------------------


@router.get("/assistant/conversations", summary="Your conversations of the last 30 days")
def conversations(user: AdminUser, db: DbSession) -> list[dict]:
    return chat.listing(db, user)


@router.get("/assistant/conversations/{conversation_id}", summary="One conversation, as the chat shows it")
def conversation(conversation_id: int, user: AdminUser, db: DbSession) -> dict:
    return chat.view(db, _mine(db, user.id, conversation_id))


@router.delete("/assistant/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete one conversation")
def delete_conversation(conversation_id: int, user: AdminUser, db: DbSession) -> None:
    db.delete(_mine(db, user.id, conversation_id))
    db.commit()


@router.delete("/assistant/conversations", status_code=status.HTTP_204_NO_CONTENT, summary="Delete all your conversations")
def delete_conversations(user: AdminUser, db: DbSession) -> None:
    for row in db.query(Conversation).filter(Conversation.user_id == user.id):
        db.delete(row)
    db.commit()


@router.post("/assistant/conversations/{conversation_id}/allow", summary="Allow the assistant something in this conversation")
def allow(conversation_id: int, body: Grant, user: AdminUser, db: DbSession) -> dict:
    found = _mine(db, user.id, conversation_id)
    try:
        chat.allow(db, found, body.grant)
    except providers.AssistantError as failure:
        raise _refusal(failure) from None
    logger.info("%s allowed the assistant %s in conversation %d.", user.username, body.grant, found.id)
    return {"grants": found.grants}


@router.post("/assistant/chat", summary="Ask the assistant")
async def ask(body: Question, user: AdminUser, db: DbSession) -> dict:
    if not settings.ready(db):
        raise error("off", "The assistant is not set up.", status.HTTP_409_CONFLICT)
    if user.id in _busy:
        raise error("busy", "The assistant is still answering your last question.", status.HTTP_409_CONFLICT)
    _busy.add(user.id)
    try:
        try:
            found = chat.open_conversation(db, user, body.conversation_id, body.text)
            reply = await chat.answer(db, user, found, body.text.strip(), about=body.about)
        except providers.AssistantError as failure:
            logger.warning("The assistant could not answer %s: %s", user.username, failure.message)
            raise _refusal(failure) from None
        except asyncio.CancelledError:
            logger.info("%s left before the assistant answered.", user.username)
            raise
    finally:
        _busy.discard(user.id)
    return {"conversation_id": found.id, **reply}
