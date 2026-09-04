"""Web Push: the public key and the browser's subscription."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, error
from ..models import NotificationChannel, Subscription
from ..schemas import PushSubscribeBody, PushUnsubscribeBody
from ..services.channels import webpush

router = APIRouter(prefix="/api/v1/push", tags=["push"])


@router.get("/key", summary="Read the public VAPID key")
def public_key(user: CurrentUser) -> dict:
    return {"key": webpush.public_key()}


@router.post("/subscribe", status_code=status.HTTP_201_CREATED, summary="Register this browser for Web Push")
def subscribe(body: PushSubscribeBody, request: Request, user: CurrentUser, db: DbSession) -> dict:
    """Also creates the account's Web Push channel on first use."""
    try:
        webpush.store_subscription(user.id, body.subscription, request.headers.get("user-agent", ""))
    except ValueError as failure:
        raise error("bad_subscription", str(failure)) from failure
    channel = db.scalar(select(NotificationChannel).where(NotificationChannel.user_id == user.id, NotificationChannel.kind == "webpush"))
    if channel is None:
        channel = NotificationChannel(user_id=user.id, kind="webpush", name="Web Push", config={}, enabled=True)
        db.add(channel)
        db.flush()
        for event in ("outage", "recovery", "action_failed"):
            db.add(Subscription(channel_id=channel.id, event=event))
        db.commit()
    return {"ok": True, "channel_id": channel.id}


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT, summary="Remove this browser's Web Push subscription")
def unsubscribe(body: PushUnsubscribeBody, user: CurrentUser) -> None:
    webpush.remove_subscription(user.id, body.endpoint)
