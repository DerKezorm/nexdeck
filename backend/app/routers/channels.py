"""Notification channels and their subscriptions."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, MemberUser, error
from ..models import NotificationChannel, Subscription
from ..schemas import ChannelCreate, ChannelPatch
from ..services.channels import (
    KINDS,
    kinds_payload,
    public_channel_config,
    resolve_channel_config,
    send,
    store_channel_config,
)
from ..services.notify import EVENTS, Message

router = APIRouter(prefix="/api/v1", tags=["channels"])


def _public(channel: NotificationChannel) -> dict:
    return {"id": channel.id, "kind": channel.kind, "name": channel.name, "config": public_channel_config(channel), "enabled": channel.enabled,
            "events": sorted(s.event for s in channel.subscriptions), "last_error": channel.last_error, "created_at": channel.created_at}


@router.get("/channel-kinds", summary="List channel kinds and their fields")
def channel_kinds(user: CurrentUser) -> list[dict]:
    return kinds_payload()


@router.get("/events", summary="List the events a channel can subscribe to")
def events(user: CurrentUser) -> list[dict]:
    return [{"event": key, "label": label} for key, label in EVENTS.items()]


@router.get("/channels", summary="List my notification channels")
def list_channels(user: CurrentUser, db: DbSession) -> list[dict]:
    return [_public(c) for c in db.scalars(select(NotificationChannel).where(NotificationChannel.user_id == user.id).order_by(NotificationChannel.id))]


def _own(db: DbSession, channel_id: int, user: CurrentUser) -> NotificationChannel:
    channel = db.get(NotificationChannel, channel_id)
    if channel is None or channel.user_id != user.id:
        raise error("not_found", "There is no such channel.", status.HTTP_404_NOT_FOUND)
    return channel


def _set_events(db: DbSession, channel: NotificationChannel, events: list[str]) -> None:
    wanted = {e for e in events if e in EVENTS}
    for sub in list(channel.subscriptions):
        if sub.event not in wanted:
            db.delete(sub)
        else:
            wanted.discard(sub.event)
    for event in wanted:
        db.add(Subscription(channel_id=channel.id, event=event))


@router.post("/channels", status_code=status.HTTP_201_CREATED, summary="Add a notification channel")
def create_channel(body: ChannelCreate, user: MemberUser, db: DbSession) -> dict:
    if body.kind not in KINDS:
        raise error("unknown_kind", f"There is no channel kind {body.kind!r}.")
    channel = NotificationChannel(user_id=user.id, kind=body.kind, name=body.name.strip(), config=store_channel_config(body.kind, body.config), enabled=body.enabled)
    db.add(channel)
    db.flush()
    _set_events(db, channel, body.events or ["outage", "recovery", "action_failed"])
    db.commit()
    db.refresh(channel)
    return _public(channel)


@router.patch("/channels/{channel_id}", summary="Change a notification channel")
def patch_channel(channel_id: int, body: ChannelPatch, user: MemberUser, db: DbSession) -> dict:
    channel = _own(db, channel_id, user)
    if body.name is not None:
        channel.name = body.name.strip()
    if body.config is not None:
        channel.config = store_channel_config(channel.kind, body.config, channel.config)
    if body.enabled is not None:
        channel.enabled = body.enabled
    if body.events is not None:
        _set_events(db, channel, body.events)
    channel.last_error = ""
    db.commit()
    db.refresh(channel)
    return _public(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a notification channel")
def delete_channel(channel_id: int, user: MemberUser, db: DbSession) -> None:
    channel = _own(db, channel_id, user)
    db.delete(channel)
    db.commit()


@router.post("/channels/{channel_id}/test", summary="Send a test message through a channel")
async def test_channel(channel_id: int, user: MemberUser, db: DbSession) -> dict:
    channel = _own(db, channel_id, user)
    message = Message(event="test", title="nexdeck test message", body="If you can read this, the channel works.", level="info")
    try:
        await send(channel.kind, resolve_channel_config(channel), message, user_id=user.id)
    except Exception as failure:  # noqa: BLE001
        channel.last_error = str(failure)[:300]
        db.commit()
        return {"ok": False, "message": str(failure)}
    channel.last_error = ""
    db.commit()
    return {"ok": True, "message": "Sent."}
