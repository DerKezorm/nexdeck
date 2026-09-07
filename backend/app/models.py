"""The database schema.

Boards contain pages, pages contain widgets, widgets reference integrations.
An integration is one configured connection to a service ("my Radarr"); many
widgets can share it, and the collector polls it once for all of them.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Utc(TypeDecorator[datetime]):
    """A moment in time that still knows it is UTC after a round trip.

    ⚠️ SQLite has no type for this. ``DateTime(timezone=True)`` writes the
    text and drops the offset, so every value read back was naive. Comparing
    one against ``datetime.now(UTC)`` raises TypeError, and serialised to JSON
    it lost its ``Z``, which made the browser read it as local time: the same
    notice showed one time live and another after a reload, off by the zone.

    Both follow from the same missing marker, so both are fixed here rather
    than at each of the places that read a timestamp.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Role(enum.StrEnum):
    admin = "admin"
    user = "user"
    guest = "guest"


class ShareLevel(enum.StrEnum):
    view = "view"
    edit = "edit"
    act = "act"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default=Role.user.value)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    theme: Mapped[str] = mapped_column(String(8), default="dark")
    start_board_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    #: Milliseconds; sessions issued before this moment are invalid.
    password_changed_ms: Mapped[int] = mapped_column(Integer, default=0)
    #: Which "what's new" version the user has already seen.
    #: The second factor. The secret is encrypted; ``confirmed`` only turns
    #: true once somebody has typed a code the secret produced, so a half-done
    #: setup cannot lock anybody out.
    totp_secret: Mapped[str] = mapped_column(Text, default="")
    totp_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ⚠️ The last accepted time step. A code that was good once is never good
    #: again; without this an intercepted code works for another half minute,
    #: which is longer than anybody needs to pass it on.
    totp_last_step: Mapped[int] = mapped_column(Integer, default=0)
    seen_version: Mapped[str] = mapped_column(String(16), default="")
    #: File name of the profile picture in ``data/avatars``; empty means none.
    avatar: Mapped[str] = mapped_column(String(120), default="")
    #: Where a password reset would go. Optional, unique when set.
    email: Mapped[str] = mapped_column(String(200), default="")

    sessions: Mapped[list[Session]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_tokens: Mapped[list[ApiToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recovery_codes: Mapped[list[RecoveryCode]] = relationship(back_populates="user", cascade="all, delete-orphan")
    oidc_links: Mapped[list[OidcLink]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="sessions")


class RecoveryCode(Base):
    """One way back in when the phone with the codes on it is gone."""

    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    #: ⚠️ Used means used, and the row stays. Deleting it would be tidier and
    #: would throw away the answer to "how many do I have left".
    used_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)

    user: Mapped[User] = relationship(back_populates="recovery_codes")


class PasswordReset(Base):
    """A one-time way back in, sent by mail.

    ⚠️ Only the hash is stored, like every other token here. A reset link out
    of a database dump would be a way into every account at once.
    """

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Utc())
    used_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    #: When the token stops working. Empty means it does not expire on its own.
    expires_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    #: Withdrawn. The row stays so the hash can never come back and a list can
    #: still say what happened to it.
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)

    user: Mapped[User] = relationship(back_populates="api_tokens")


class OidcProvider(Base):
    __tablename__ = "oidc_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    issuer_url: Mapped[str] = mapped_column(String(300))
    client_id: Mapped[str] = mapped_column(String(300))
    client_secret: Mapped[str] = mapped_column(String(600))
    scopes: Mapped[str] = mapped_column(String(200), default="openid profile email")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Create an account on first sign-in, with this role.
    auto_create: Mapped[bool] = mapped_column(Boolean, default=True)
    default_role: Mapped[str] = mapped_column(String(16), default=Role.user.value)
    #: This provider asks for a second factor itself, so nexdeck does not.
    #:
    #: ⚠️ Off by default, which is the safe way round: until 07.09.2026 the
    #: OIDC return path opened a session outright, so an account with a
    #: confirmed authenticator app was let in without a code as long as it came
    #: through a provider. Whoever runs authentik or Authelia with MFA in front
    #: ticks this and is not asked twice. nexdeck cannot find it out by itself.
    trusts_second_factor: Mapped[bool] = mapped_column(Boolean, default=False)


class OidcLink(Base):
    __tablename__ = "oidc_links"
    __table_args__ = (UniqueConstraint("provider_id", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("oidc_providers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    email: Mapped[str] = mapped_column(String(300), default="")

    user: Mapped[User] = relationship(back_populates="oidc_links")


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str] = mapped_column(String(80), default="layout-dashboard")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: ``{"kind": "bundled"|"upload"|"gradient"|"none", "value": str, "blur": int, "dim": int}``
    background: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Free-form board settings: density, accent override, kiosk defaults.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: Whether the board stands in the menu at the top. Off is not hidden: the
    #: board list still holds it, and its address still works.
    in_menu: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Boards read from ``data/boards/*.yaml`` are shown but not editable.
    provisioned: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow, onupdate=utcnow)

    pages: Mapped[list[Page]] = relationship(
        back_populates="board", cascade="all, delete-orphan", order_by="Page.position"
    )
    shares: Mapped[list[BoardShare]] = relationship(back_populates="board", cascade="all, delete-orphan")
    kiosk_tokens: Mapped[list[KioskToken]] = relationship(back_populates="board", cascade="all, delete-orphan")


class BoardShare(Base):
    """Who else may see, edit or act on a board.

    Either a specific user or a whole role. ``level`` is the permission.
    """

    __tablename__ = "board_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    level: Mapped[str] = mapped_column(String(8), default=ShareLevel.view.value)

    board: Mapped[Board] = relationship(back_populates="shares")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str] = mapped_column(String(80), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: ``{"lg": [{"i": "<widget id>", "x", "y", "w", "h"}], "md": [...], "sm": [...]}``
    layouts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Optional named sections: ``[{"id", "title", "y"}]``
    sections: Mapped[list[Any]] = mapped_column(JSON, default=list)

    board: Mapped[Board] = relationship(back_populates="pages")
    widgets: Mapped[list[Widget]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="Widget.id"
    )


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    #: Adapter config; fields flagged secret are stored encrypted.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Demo mode: the adapter's fake data instead of the real service.
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Locked: only administrators may build cards on this connection. Users
    #: still see its cards on a board that was shared with them.
    admin_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

    widgets: Mapped[list[Widget]] = relationship(back_populates="integration")


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    #: ``<adapter>.<widget>``, e.g. ``docker.containers`` or ``core.clock``.
    kind: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    icon: Mapped[str] = mapped_column(String(200), default="")
    link: Mapped[str] = mapped_column(String(600), default="")
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    refresh_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)

    page: Mapped[Page] = relationship(back_populates="widgets")
    integration: Mapped[Integration | None] = relationship(back_populates="widgets")
    health_check: Mapped[HealthCheck | None] = relationship(
        back_populates="widget", cascade="all, delete-orphan", uselist=False
    )


class KioskToken(Base):
    __tablename__ = "kiosk_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    allow_actions: Mapped[bool] = mapped_column(Boolean, default=False)
    #: 0 means no automatic page cycling.
    cycle_seconds: Mapped[int] = mapped_column(Integer, default=0)
    #: ``HH:MM`` local times; empty means no dimming.
    dim_from: Mapped[str] = mapped_column(String(5), default="")
    dim_to: Mapped[str] = mapped_column(String(5), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    #: When the display stops being let in. Empty means no end.
    expires_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    #: Withdrawn. Deleting the link sets this instead of removing the row, so a
    #: withdrawn token can never be granted again and the cookie it handed out
    #: stops working at the next request.
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)

    board: Mapped[Board] = relationship(back_populates="kiosk_tokens")


class HistorySample(Base):
    """Raw numeric samples, kept for a short window."""

    __tablename__ = "history_samples"
    __table_args__ = (Index("ix_history_samples_key_ts", "key", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``<widget id>:<metric>``
    key: Mapped[str] = mapped_column(String(120))
    ts: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)


class HistoryMinute(Base):
    """Minute averages, kept for a day."""

    __tablename__ = "history_minutes"
    __table_args__ = (UniqueConstraint("key", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    ts: Mapped[int] = mapped_column(Integer)
    avg: Mapped[float] = mapped_column(Float)
    min: Mapped[float] = mapped_column(Float)
    max: Mapped[float] = mapped_column(Float)
    count: Mapped[int] = mapped_column(Integer)


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    widget_id: Mapped[int | None] = mapped_column(
        ForeignKey("widgets.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    kind: Mapped[str] = mapped_column(String(8), default="http")
    target: Mapped[str] = mapped_column(String(600))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    #: For HTTP: accept this status (0 means any 2xx or 3xx).
    expect_status: Mapped[int] = mapped_column(Integer, default=0)
    #: Skip TLS verification for self-signed services.
    insecure: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    down_since: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)

    widget: Mapped[Widget | None] = relationship(back_populates="health_check")
    outages: Mapped[list[Outage]] = relationship(back_populates="check", cascade="all, delete-orphan")


class Outage(Base):
    __tablename__ = "outages"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("health_checks.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(Utc())
    ended_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    announced: Mapped[bool] = mapped_column(Boolean, default=False)

    check: Mapped[HealthCheck] = relationship(back_populates="outages")


class LogLine(Base):
    __tablename__ = "log_lines"
    __table_args__ = (Index("ix_log_lines_source_ts", "source", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``<integration id>:<container id>``
    source: Mapped[str] = mapped_column(String(160))
    ts: Mapped[float] = mapped_column(Float)
    line: Mapped[str] = mapped_column(Text)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_error: Mapped[str] = mapped_column(String(300), default="")

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("channel_id", "event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(40))

    channel: Mapped[NotificationChannel] = relationship(back_populates="subscriptions")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(300))
    auth: Mapped[str] = mapped_column(String(300))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Notice(Base):
    """The in-app notice centre. ``user_id`` empty means: every admin."""

    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(8), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(600), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)


class ActionLog(Base):
    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor: Mapped[str] = mapped_column(String(120))
    widget_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    integration_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
