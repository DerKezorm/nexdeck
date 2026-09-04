"""Web Push: RFC 8291 encryption and RFC 8292 VAPID signatures.

The VAPID key pair belongs to the installation; it is generated once and kept
in the settings table. Every browser subscription is bound to its public
half, so a new pair would mean every device has to subscribe again.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from sqlalchemy import select

from ...config import get_settings
from ...crypto import decrypt, encrypt
from ...db import db_session
from ...models import PushSubscription, Setting
from ..notify import Message

logger = logging.getLogger("nexdeck.webpush")

SETTING_KEY = "vapid"
TTL_SECONDS = 24 * 3600
BODY_LIMIT = 3000


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _raw(b64url: str) -> bytes:
    return base64.urlsafe_b64decode(b64url + "=" * (-len(b64url) % 4))


def ensure_keys() -> tuple[str, str]:
    """Return ``(private_pem, public_key_b64url)``, generating them once."""
    with db_session() as db:
        setting = db.get(Setting, SETTING_KEY)
        if setting is not None and setting.value.get("private"):
            private_pem = decrypt(setting.value["private"])
            return private_pem, setting.value["public"]
        key = ec.generate_private_key(ec.SECP256R1())
        private_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        public_raw = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        public = _b64url(public_raw)
        db.merge(Setting(key=SETTING_KEY, value={"private": encrypt(private_pem), "public": public}))
        return private_pem, public


def public_key() -> str:
    return ensure_keys()[1]


def subject() -> str:
    public_url = get_settings().public_url
    if public_url.startswith("https://"):
        url = httpx.URL(public_url)
        return f"https://{url.netloc.decode()}"
    return "mailto:admin@localhost"


def payload(message: Message) -> bytes:
    data = {
        "title": message.title[:120],
        "body": (message.body or "")[:160],
        "url": message.link or "/",
        "tag": f"{message.event}:{message.title[:60]}",
        "level": message.level,
    }
    return json.dumps(data, ensure_ascii=False).encode()[:BODY_LIMIT]


async def send_one(endpoint: str, p256dh: str, auth: str, message: Message) -> bool:
    """Send to one subscription. Returns False when the subscription is gone."""
    private_pem, _ = ensure_keys()
    endpoint_url = httpx.URL(endpoint)
    signer = Vapid02.from_pem(private_pem.encode())
    headers = signer.sign({
        "aud": f"{endpoint_url.scheme}://{endpoint_url.netloc.decode()}",
        "sub": subject(),
        "exp": int(time.time()) + 12 * 3600,
    })
    headers.update({
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        "Urgency": "high" if message.level == "error" else "normal",
    })
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    body = http_ece.encrypt(payload(message), private_key=ephemeral, dh=_raw(p256dh), auth_secret=_raw(auth), version="aes128gcm")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(endpoint, content=body, headers=headers)
    if response.status_code in (404, 410):
        return False
    if response.status_code >= 400:
        raise RuntimeError(f"The push service answered with HTTP {response.status_code}.")
    return True


async def send_to_user(user_id: int | None, message: Message) -> None:
    if user_id is None:
        return
    with db_session() as db:
        subscriptions = [
            (s.id, s.endpoint, s.p256dh, decrypt(s.auth))
            for s in db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
        ]
    if not subscriptions:
        raise RuntimeError("No browser has subscribed to Web Push for this account yet.")
    gone: list[int] = []
    errors: list[str] = []
    for sub_id, endpoint, p256dh, auth in subscriptions:
        try:
            if not await send_one(endpoint, p256dh, auth, message):
                gone.append(sub_id)
        except Exception as error:  # noqa: BLE001
            errors.append(str(error))
    if gone:
        with db_session() as db:
            for sub_id in gone:
                row = db.get(PushSubscription, sub_id)
                if row is not None:
                    db.delete(row)
    if errors and len(errors) == len(subscriptions):
        raise RuntimeError(errors[0])


def store_subscription(user_id: int, data: dict[str, Any], user_agent: str) -> None:
    endpoint = str(data.get("endpoint") or "")
    keys = data.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("The subscription is incomplete.")
    with db_session() as db:
        existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if existing is None:
            db.add(PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=keys["p256dh"],
                                    auth=encrypt(keys["auth"]), user_agent=user_agent[:300]))
        else:
            existing.user_id = user_id
            existing.p256dh = keys["p256dh"]
            existing.auth = encrypt(keys["auth"])


def remove_subscription(user_id: int, endpoint: str) -> None:
    with db_session() as db:
        existing = db.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user_id)
        )
        if existing is not None:
            db.delete(existing)
