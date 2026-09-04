"""Notification channels: Telegram, e-mail, Web Push, ntfy, Gotify, Discord, Slack, Apprise.

Every kind declares its fields and implements ``send``. Secrets are stored
encrypted like integration secrets and decrypted here, right before use.
"""

from __future__ import annotations

import asyncio
import json
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import httpx

from ...adapters.base import Field
from ...crypto import decrypt, encrypt
from ...db import db_session
from ...models import NotificationChannel
from ..notify import Message

TIMEOUT = 15.0


@dataclass(frozen=True)
class ChannelKind:
    kind: str
    label: str
    fields: tuple[Field, ...]
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "label": self.label, "help": self.help, "fields": [f.to_dict() for f in self.fields]}


KINDS: dict[str, ChannelKind] = {
    "telegram": ChannelKind(
        "telegram", "Telegram",
        (Field("bot_token", "Bot token", type="password", secret=True, required=True),
         Field("chat_id", "Chat ID", required=True, placeholder="123456789")),
        "Create a bot with @BotFather, then write to it once and read the chat ID from getUpdates.",
    ),
    "email": ChannelKind(
        "email", "E-mail",
        (Field("host", "SMTP server", required=True, placeholder="smtp.example.com"),
         Field("port", "Port", type="number", default=587),
         Field("username", "User name"),
         Field("password", "Password", type="password", secret=True),
         Field("from_address", "From address", required=True, placeholder="deck@example.com"),
         Field("to_address", "To address", required=True, placeholder="you@example.com"),
         Field("tls", "Encryption", type="select", default="starttls", options=(("starttls", "STARTTLS"), ("ssl", "SSL"), ("none", "None")))),
    ),
    "webpush": ChannelKind(
        "webpush", "Web Push",
        (),
        "Subscribed from the browser or the installed app; nothing to fill in here.",
    ),
    "ntfy": ChannelKind(
        "ntfy", "ntfy",
        (Field("url", "Server URL", type="url", required=True, default="https://ntfy.sh"),
         Field("topic", "Topic", required=True),
         Field("token", "Access token", type="password", secret=True)),
    ),
    "gotify": ChannelKind(
        "gotify", "Gotify",
        (Field("url", "Server URL", type="url", required=True),
         Field("token", "App token", type="password", secret=True, required=True)),
    ),
    "discord": ChannelKind(
        "discord", "Discord",
        (Field("webhook", "Webhook URL", type="password", secret=True, required=True),),
    ),
    "slack": ChannelKind(
        "slack", "Slack",
        (Field("webhook", "Webhook URL", type="password", secret=True, required=True),),
    ),
    "apprise": ChannelKind(
        "apprise", "Apprise",
        (Field("urls", "Apprise URLs", type="textarea", secret=True, required=True,
               help="One per line, e.g. pover://user@token or mailto://...")),
        "One channel, a hundred services. See the Apprise documentation for URL formats.",
    ),
}

LEVEL_EMOJI = {"info": "", "warn": "⚠️ ", "error": "🔴 "}


def store_channel_config(kind: str, incoming: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(existing or {})
    for f in KINDS[kind].fields:
        if f.name not in incoming:
            if f.name not in result and f.default is not None:
                result[f.name] = f.default
            continue
        value = incoming[f.name]
        if f.secret:
            if value in (None, "", "********"):
                continue
            result[f.name] = encrypt(str(value))
        else:
            result[f.name] = value
    return result


def public_channel_config(channel: NotificationChannel) -> dict[str, Any]:
    config = dict(channel.config or {})
    for f in KINDS.get(channel.kind, KINDS["ntfy"]).fields:
        if f.secret:
            config[f.name] = "********" if config.get(f.name) else ""
    return config


def resolve_channel_config(channel: NotificationChannel) -> dict[str, Any]:
    config = dict(channel.config or {})
    for f in KINDS.get(channel.kind, KINDS["ntfy"]).fields:
        if f.secret and isinstance(config.get(f.name), str):
            config[f.name] = decrypt(config[f.name])
    return config


def plain_text(message: Message) -> str:
    text = f"{LEVEL_EMOJI.get(message.level, '')}{message.title}"
    if message.body:
        text += f"\n{message.body}"
    if message.link:
        text += f"\n{message.link}"
    return text


async def send_to_channel(channel_id: int, message: Message) -> None:
    with db_session() as db:
        channel = db.get(NotificationChannel, channel_id)
        if channel is None or not channel.enabled:
            return
        kind = channel.kind
        config = resolve_channel_config(channel)
        user_id = channel.user_id
    await send(kind, config, message, user_id=user_id)
    with db_session() as db:
        channel = db.get(NotificationChannel, channel_id)
        if channel is not None:
            channel.last_error = ""


async def send(kind: str, config: dict[str, Any], message: Message, *, user_id: int | None = None) -> None:
    if kind == "telegram":
        await _telegram(config, message)
    elif kind == "email":
        await asyncio.to_thread(_email, config, message)
    elif kind == "webpush":
        from . import webpush

        await webpush.send_to_user(user_id, message)
    elif kind == "ntfy":
        await _ntfy(config, message)
    elif kind == "gotify":
        await _gotify(config, message)
    elif kind == "discord":
        await _discord(config, message)
    elif kind == "slack":
        await _slack(config, message)
    elif kind == "apprise":
        await asyncio.to_thread(_apprise, config, message)
    else:
        raise ValueError(f"Unknown channel kind {kind!r}.")


async def _post(url: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"The service answered with HTTP {response.status_code}.")
    return response


async def _telegram(config: dict[str, Any], message: Message) -> None:
    await _post(
        f"https://api.telegram.org/bot{config['bot_token']}/sendMessage",
        json={"chat_id": config["chat_id"], "text": plain_text(message), "disable_web_page_preview": True},
    )


def _email(config: dict[str, Any], message: Message) -> None:
    mail = EmailMessage()
    mail["Subject"] = f"[nexdeck] {message.title}"
    mail["From"] = config["from_address"]
    mail["To"] = config["to_address"]
    mail.set_content(plain_text(message))
    port = int(config.get("port") or 587)
    mode = config.get("tls") or "starttls"
    if mode == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(config["host"], port, timeout=TIMEOUT)
    else:
        server = smtplib.SMTP(config["host"], port, timeout=TIMEOUT)
    with server:
        if mode == "starttls":
            server.starttls()
        if config.get("username"):
            server.login(config["username"], config.get("password") or "")
        server.send_message(mail)


async def _ntfy(config: dict[str, Any], message: Message) -> None:
    headers = {"Title": message.title.encode("ascii", "ignore").decode(), "Priority": {"error": "high", "warn": "default"}.get(message.level, "default")}
    if config.get("token"):
        headers["Authorization"] = f"Bearer {config['token']}"
    if message.link:
        headers["Click"] = message.link
    await _post(f"{str(config['url']).rstrip('/')}/{config['topic']}", content=(message.body or message.title).encode(), headers=headers)


async def _gotify(config: dict[str, Any], message: Message) -> None:
    priority = {"error": 8, "warn": 5}.get(message.level, 3)
    await _post(
        f"{str(config['url']).rstrip('/')}/message",
        params={"token": config["token"]},
        json={"title": message.title, "message": message.body or message.title, "priority": priority},
    )


async def _discord(config: dict[str, Any], message: Message) -> None:
    colour = {"error": 0xE11D48, "warn": 0xF59E0B}.get(message.level, 0x22D3EE)
    embed: dict[str, Any] = {"title": message.title, "description": message.body, "color": colour}
    if message.link:
        embed["url"] = message.link
    await _post(config["webhook"], json={"username": "nexdeck", "embeds": [embed]})


async def _slack(config: dict[str, Any], message: Message) -> None:
    await _post(config["webhook"], json={"text": plain_text(message)})


def _apprise(config: dict[str, Any], message: Message) -> None:
    import apprise

    notifier = apprise.Apprise()
    for line in str(config.get("urls") or "").splitlines():
        if line.strip():
            notifier.add(line.strip())
    kind = {"error": apprise.NotifyType.FAILURE, "warn": apprise.NotifyType.WARNING}.get(message.level, apprise.NotifyType.INFO)
    if not notifier.notify(title=message.title, body=message.body or message.title, notify_type=kind):
        raise RuntimeError("Apprise reported that no service accepted the message.")


def kinds_payload() -> list[dict[str, Any]]:
    return [k.to_dict() for k in KINDS.values()]


def dumps(value: Any) -> str:
    return json.dumps(value)
