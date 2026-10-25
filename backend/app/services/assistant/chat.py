"""One answer of the assistant: the question in, tools in a loop, the answer out, all of it kept.

A conversation is stored entry by entry (``ConversationTurn``) and read back
for the next question, so it can be continued on another device. It goes
away 30 days after its last turn (``sweep``, called by the retention round).

⚠️ Every entry is committed as soon as it is written. An answer waits on the
provider for up to two minutes a turn, and an open write on SQLite would hold
every other writer of the installation for that long.

⚠️ At most a few rounds of tools per answer. A model that keeps calling them
costs the operator money and the person their patience; after the last
round the answer is what the model has said so far.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...models import Conversation, ConversationTurn, User, utcnow
from . import providers, settings, tools

logger = logging.getLogger("nexdeck.assistant")

#: Rounds of tool calls in one answer.
MAX_ROUNDS = 8
#: Earlier entries of a conversation sent along with a new question.
MAX_HISTORY = 60
KEEP_DAYS = 30

LANGUAGES = {"de": "German", "en": "English", "es": "Spanish", "fr": "French", "it": "Italian"}

SYSTEM = """You are the assistant inside nexdeck, a self-hosted dashboard for a homelab. An administrator asks you about their services, servers and network.

Answer from what the tools return, never from what you guess. If the tools do not show it, say that you cannot see it. Look things up before you answer: needs_attention for what is wrong, chronicle for what happened and what changed before something broke, find_cards and card_details for one service, diagnosis for why one service is broken, metric_history for how a number moved.

You never press a button. When something should be done, find the card that offers it with card_details and call propose_action; the person then sees the button with what it would hit and decides. Say in one sentence what the button does and never claim it ran. A stop, a deletion or a shutdown is marked as dangerous; mention what it costs.

A container's log is read only after the person allowed it in this conversation. When a log would help, call container_log right away instead of offering it in words: the call itself puts the question in front of the person, with a button to allow it. If it says you asked, say in one sentence that you need their permission, and stop there.

Keep answers short: a few sentences or a short list. Name times as the person reads them (14:32, yesterday 22:10). Use **bold** for names that matter and "- " for list items; no headings, no tables, no links. Answer in {language}."""


def system_for(user: User) -> str:
    return SYSTEM.replace("{language}", LANGUAGES.get((user.locale or "en").split("-")[0], "English"))


def transcript(db: Session, conversation: Conversation) -> list[dict[str, Any]]:
    turns = list(db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation.id).order_by(ConversationTurn.id)))
    entries = [{**turn.content, "role": turn.role, "provider": turn.provider, "raw": turn.raw} for turn in turns]
    for entry in entries:
        if entry["role"] == "user" and entry.get("note"):
            entry["text"] = f"{entry['text']}\n\n{entry['note']}"
    # ⚠️ Cut only before a question: a tool result without the call it answers
    # is refused by every provider.
    if len(entries) > MAX_HISTORY:
        cut = len(entries) - MAX_HISTORY
        while cut < len(entries) and entries[cut]["role"] != "user":
            cut += 1
        entries = entries[cut:]
    return entries


def _add(db: Session, conversation: Conversation, role: str, content: dict[str, Any], provider: str = "", raw: list[Any] | None = None) -> None:
    db.add(ConversationTurn(conversation_id=conversation.id, role=role, content=content, provider=provider, raw=raw))
    conversation.updated_at = utcnow()
    db.commit()


def open_conversation(db: Session, user: User, conversation_id: int | None, first_words: str) -> Conversation:
    if conversation_id is not None:
        found = db.get(Conversation, conversation_id)
        if found is None or found.user_id != user.id:
            raise providers.AssistantError("not_found", "No such conversation.")
        return found
    conversation = Conversation(user_id=user.id, title=" ".join(first_words.split())[:200], grants=[])
    db.add(conversation)
    db.commit()
    return conversation


def _from_page(db: Session, about: str | None) -> str:
    """The note that tells the model which diagnosis page the question comes from, or ""."""
    from .. import diagnosis

    if not about or diagnosis.subject(db, about) is None:
        return ""
    return f"(Asked on the diagnosis page of {diagnosis.subject(db, about)['name']}, ref {about}. Call diagnosis with that ref first.)"


async def answer(db: Session, user: User, conversation: Conversation, question: str, about: str | None = None) -> dict[str, Any]:
    """Put the question to the provider and run its tools until it answers."""
    config = settings.stored(db)
    if not settings.ready(db):
        raise providers.AssistantError("off", "The assistant is not set up.")
    key = settings.key_of(db)
    note = _from_page(db, about)
    # The note goes to the model with the question; the chat shows the question as it was typed.
    _add(db, conversation, "user", {"text": question, **({"about": about, "note": note} if note else {})})
    bench = tools.Bench(db=db, user=user, grants=list(conversation.grants or []))
    entries = transcript(db, conversation)
    text, refused, spent = "", False, [0, 0]
    for round_number in range(MAX_ROUNDS):
        turn = await providers.turn(config, key, system_for(user), entries, tools.TOOLS)
        spent[0] += turn.tokens_in
        spent[1] += turn.tokens_out
        entry = {"text": turn.text, "calls": turn.calls}
        _add(db, conversation, "assistant", entry, config["provider"], turn.raw)
        entries.append({**entry, "role": "assistant", "provider": config["provider"], "raw": turn.raw})
        if turn.text:
            text = turn.text
        if turn.stop == "refusal":
            refused = True
            break
        if not turn.calls:
            break
        results = []
        for call in turn.calls:
            content, failed = await tools.run(bench, call["name"], call["input"])
            results.append({"id": call["id"], "content": content, "is_error": failed})
        _add(db, conversation, "tool", {"results": results})
        entries.append({"role": "tool", "results": results})
        if round_number == MAX_ROUNDS - 1:
            logger.info("The assistant used all %d rounds of tools for one answer.", MAX_ROUNDS)
    reply = {
        "text": text, "refused": refused,
        "citations": list(bench.citations.values()), "proposals": bench.proposals, "permissions": bench.permissions,
    }
    _add(db, conversation, "answer", reply)
    logger.info("The assistant answered %s (%s, %d tokens in, %d out).", user.username, config["model"], spent[0], spent[1])
    return reply


def allow(db: Session, conversation: Conversation, grant: str) -> None:
    """What the person allowed in this conversation, such as reading one container's log."""
    if not grant.startswith("log:"):
        raise providers.AssistantError("bad_grant", "Nothing like that can be allowed.")
    conversation.grants = sorted({*(conversation.grants or []), grant})
    db.commit()


def view(db: Session, conversation: Conversation) -> dict[str, Any]:
    """A conversation as the chat shows it again: the questions and the answers, no tool traffic."""
    shown = []
    for turn in db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation.id).order_by(ConversationTurn.id)):
        if turn.role == "user":
            shown.append({"me": True, "text": turn.content.get("text", "")})
        elif turn.role == "answer":
            shown.append({"me": False, **turn.content})
    return {"id": conversation.id, "title": conversation.title, "updated_at": conversation.updated_at.isoformat(), "turns": shown}


def listing(db: Session, user: User) -> list[dict[str, Any]]:
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(100))
    return [{"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat()} for row in rows]


def sweep(db: Session) -> int:
    """Conversations whose last turn is older than 30 days go, with their turns."""
    old = list(db.scalars(select(Conversation.id).where(Conversation.updated_at < utcnow() - timedelta(days=KEEP_DAYS))))
    if old:
        db.execute(delete(ConversationTurn).where(ConversationTurn.conversation_id.in_(old)))
        db.execute(delete(Conversation).where(Conversation.id.in_(old)))
    return len(old)
