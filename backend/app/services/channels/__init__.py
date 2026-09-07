"""Notification channels: Telegram, e-mail, Web Push, ntfy, Gotify, Discord, Slack, Apprise.

Every kind declares its fields and implements ``send``. Secrets are stored
encrypted like integration secrets and decrypted here, right before use.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from ...adapters.base import Field, guard_member_target, outbound_client
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
    # ⚠️ One field. It used to ask for the host, the port, the user name, the
    # password, the sender and the recipient, which is the installation's own
    # mail account typed out again per channel, password included. The server
    # has those already; a channel only needs to know where to write.
    "email": ChannelKind(
        "email", "E-mail",
        (Field("to_address", "To address", placeholder="you@example.com",
               help="Empty means the address on your account."),),
        "Sent through the mail server of this installation, set up under System, Mail server.",
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
               help="One per line, e.g. pover://user@token or mailto://..."),),
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
        await asyncio.to_thread(_email, config, message, user_id)
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
    # ⚠️ Every address that reaches here was typed into a channel by whoever
    # set it up, and every member may set one up. The answer comes back to
    # them as an HTTP status, so without this the field is a way of asking
    # what is listening beside the server.
    guard_member_target(url)
    async with outbound_client(timeout=TIMEOUT) as client:
        response = await client.post(url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"The service answered with HTTP {response.status_code}.")
    return response


async def _telegram(config: dict[str, Any], message: Message) -> None:
    await _post(
        f"https://api.telegram.org/bot{config['bot_token']}/sendMessage",
        json={"chat_id": config["chat_id"], "text": plain_text(message), "disable_web_page_preview": True},
    )


def _email(config: dict[str, Any], message: Message, user_id: int | None = None) -> None:
    """Through the installation's own mail server.

    ⚠️ Nothing about the server is read from the channel any more. A channel
    made before this still carries a host and a password in its settings;
    those are ignored, and the one set up under System is used instead, which
    is the one whose password somebody actually maintains.
    """
    from ...db import db_session
    from .. import mail as mail_service

    with db_session() as db:
        settings = mail_service.stored(db)
        if not settings.get("host"):
            raise RuntimeError("No mail server is set up. Set one up under System, Mail server.")
        to_address = str(config.get("to_address") or "").strip()
        if not to_address and user_id is not None:
            # ⚠️ The field says "Empty means the address on your account", and
            # until 07.09.2026 nothing here ever looked at the account. The
            # help text was a promise the code did not keep.
            from ...models import User

            owner = db.get(User, user_id)
            to_address = str(getattr(owner, "email", "") or "").strip()
        if not to_address:
            raise RuntimeError("No address to write to, and none on the account either.")
    mail_service.send(settings, to_address, f"[nexdeck] {message.title}", plain_text(message))


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


def kinds_payload(mail_ready: bool = True) -> list[dict[str, Any]]:
    """The channel kinds somebody may add right now.

    ⚠️ E-mail is left out when no mail server is set up. It has nothing of its
    own to configure any more, so offering it would mean a channel that looks
    finished, saves, and fails silently at the first outage. A kind that
    cannot work should not be on the list.
    """
    return [k.to_dict() for k in KINDS.values() if mail_ready or k.kind != "email"]


def dumps(value: Any) -> str:
    return json.dumps(value)
