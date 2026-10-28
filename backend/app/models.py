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
    #: The two languages in the top bar, as "en,de"; ``locale`` is one of them.
    language_pair: Mapped[str] = mapped_column(String(32), default="en,de")
    theme: Mapped[str] = mapped_column(String(8), default="dark")
    #: Whether a card tips towards the mouse pointer. Some people feel unwell
    #: with things moving under the pointer, so each account decides.
    #: ⚠️ With a default the database knows: 0.42 does not know the column and
    #: still has to create accounts on a database this version made.
    tilt: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    #: With ``theme == "schedule"``: when the light look begins and when the
    #: dark one does, ``HH:MM`` on the clock of the browser that shows it.
    light_from: Mapped[str] = mapped_column(String(5), default="07:00", server_default="07:00")
    dark_from: Mapped[str] = mapped_column(String(5), default="20:00", server_default="20:00")
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
    #: "password" for every ordinary sign-in, "home" for one opened on the home
    #: network without a password, which counts only there
    #: (``services/home_network.py``).
    kind: Mapped[str] = mapped_column(String(20), default="password")
    #: Where it was opened from, for the list an administrator reads.
    address: Mapped[str] = mapped_column(String(64), default="")

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
    #: ``read``: GET, HEAD and OPTIONS only (``deps.SAFE_METHODS``). ``full``:
    #: every right of the account. ⚠️ New tokens start at ``read``; the column
    #: default is ``full`` so that a token made before there were scopes keeps
    #: doing what its script does, and an older nexdeck can still insert rows.
    scope: Mapped[str] = mapped_column(String(8), default="read", server_default="full")

    user: Mapped[User] = relationship(back_populates="api_tokens")


class OidcProvider(Base):
    """One sign-in provider (an entry of the provider list in the shared sign-in module).

    ⚠️ Three columns keep the names nexdeck 0.36 gave them, ``issuer_url``,
    ``client_secret`` and, in ``oidc_links``, ``user_id``, for one version:
    an operator who goes back to 0.36 finds the table in the shape it reads,
    and its providers still sign people in. The attributes carry the
    module's names. ``client_secret`` holds the secret the way 0.36 reads
    it; ``client_secret_enc`` holds it under the provider's own context
    (``oidc-provider:<id>``), and nexdeck reads only that one. Every column
    0.36 does not know has a ``server_default``, so 0.36 still inserts rows.
    """

    __tablename__ = "oidc_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    issuer: Mapped[str] = mapped_column("issuer_url", String(500))
    client_id: Mapped[str] = mapped_column(String(300))
    #: The secret as nexdeck 0.36 reads it (``crypto.encrypt``), kept beside the new one for the way back.
    legacy_secret: Mapped[str] = mapped_column("client_secret", String(600), default="")
    client_secret_enc: Mapped[str] = mapped_column(Text, default="", server_default="")
    scopes: Mapped[str] = mapped_column(String(500), default="openid profile email")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: "New people get an account". ⚠️ Off by default; until 0.36.0 on, so a
    #: provider added by hand gave anybody with a login there an account here.
    #: Rows stored before keep their value.
    auto_create: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The role 0.36 gave accounts it created. Kept for the way back; nexdeck
    #: no longer offers it in the form and reads it only through
    #: ``services/oidc_store.role_for_new_account`` ("guest" stays, anything else
    #: makes members).
    default_role: Mapped[str] = mapped_column(String(16), default=Role.user.value)
    #: "The provider checks the second factor itself". On for new entries;
    #: entries from before keep the value they had, off by
    #: default until 0.36.
    trusts_second_factor: Mapped[bool] = mapped_column(Boolean, default=True)
    #: "" by hand, "authentik" set up by the authentik button (only that one is touched by it).
    managed: Mapped[str] = mapped_column(String(20), default="", server_default="")
    #: The order of the buttons on the sign-in page.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: The callback the provider knows when it is not the standard one: entries from before the list keep
    #: ``/api/v1/auth/oidc/<slug>/callback``, which their provider has registered.
    redirect_path: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True, default=utcnow)
    #: The redirect address the authentik button registered at authentik last.
    registered_redirect: Mapped[str] = mapped_column(String(500), default="", server_default="")


class OidcLink(Base):
    __tablename__ = "oidc_links"
    __table_args__ = (
        UniqueConstraint("provider_id", "subject"),
        Index("ux_oidc_links_provider_account", "provider_id", "user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("oidc_providers.id", ondelete="CASCADE"))
    #: The account (``account_id`` in the module); the column keeps the name 0.36 reads.
    account_id: Mapped[int] = mapped_column("user_id", ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    #: The ``iss`` of the token that made the link; "" for a link nexdeck 0.36 made.
    issuer: Mapped[str] = mapped_column(String(500), default="", server_default="")
    email: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)

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
    #: Counts up on every saved layout, so a second browser can be told it is
    #: working from a stand that has moved on. See ``put_layouts``.
    layout_version: Mapped[int] = mapped_column(Integer, default=0)
    #: Optional named sections: ``[{"id", "title", "y"}]``
    sections: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: "cards", the grid of cards, "topology", a network plan (``services/topology.py``),
    #: or "home", a free surface of Home Assistant controls (``services/home.py``).
    #: The server default lets an older version still add pages to this database.
    kind: Mapped[str] = mapped_column(String(16), default="cards", server_default="cards")
    #: Topology pages only: the connection, and who stands where (``topology.clean_layout``).
    topology: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    #: Home pages only: the connection, and what stands where (``home.clean_layout``).
    home: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    #: Card pages: a column beside the grid that stays put while the page scrolls
    #: (``services/holders.py``): ``{"place", "width", "cards"}``.
    side: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

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
    #: Muted: nothing this connection or its cards notice is told, neither in
    #: the bell nor on any channel. The cards keep running.
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

    widgets: Mapped[list[Widget]] = relationship(back_populates="integration")


class App(Base):
    """An app set up once and placed as a tile on any board (issue #37).

    An app tile that follows one takes its name, icon and address from here on
    every read, so an address changed once is changed on every board. An app
    has as many addresses as it is reached by, each with a label ("Proxy",
    "Tailscale", "Direct"); a tile picks one, or lets nexdeck pick the one for
    home or for the road by the network the browser is in.
    """

    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    icon: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    #: ``[{"label": "Proxy", "url": "https://paperless.home.example"}, ...]``
    addresses: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    #: The label of the address for the home networks, and for everywhere else.
    home: Mapped[str] = mapped_column(String(40), default="")
    away: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


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
    #: Minutes without a touch until the display rests on a large clock; 0 never.
    rest_minutes: Mapped[int] = mapped_column(Integer, default=0)
    #: dark, light, system or schedule, as for an account. Dark is what every
    #: display showed before it could choose, and what a link made then keeps.
    theme: Mapped[str] = mapped_column(String(8), default="dark", server_default="dark")
    light_from: Mapped[str] = mapped_column(String(5), default="07:00", server_default="07:00")
    dark_from: Mapped[str] = mapped_column(String(5), default="20:00", server_default="20:00")
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


class Thing(Base):
    """A container or a guest found on an engine or a hypervisor (roadmap M5), kept so it is known while that is down."""

    __tablename__ = "things"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``container:<integration>:<name>`` or ``guest:<integration>:<vmid>``.
    ref: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(12))
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    image: Mapped[str] = mapped_column(String(300), default="")
    state: Mapped[str] = mapped_column(String(20), default="")
    #: Where it answers: its own addresses (a guest), and the ports it publishes on its host (a container).
    addresses: Mapped[list[str]] = mapped_column(JSON, default=list)
    ports: Mapped[list[int]] = mapped_column(JSON, default=list)
    host_network: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Relation(Base):
    """"This runs on that" or "this needs that" (roadmap M5).

    ``child`` and ``parent`` are references: ``integration:<id>``,
    ``tile:<widget id>`` or a thing's ``ref``. A container belongs to its
    engine and a guest to its hypervisor without a row here.

    ``origin``: ``auto`` (address and port matched), ``suggested`` (the name
    matched), ``manual``. ``state``: ``on``, ``suggested`` (waiting for a
    yes) or ``rejected`` (said no to; never suggested again).
    """

    __tablename__ = "relations"
    __table_args__ = (UniqueConstraint("child", "parent"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    child: Mapped[str] = mapped_column(String(200), index=True)
    parent: Mapped[str] = mapped_column(String(200), index=True)
    origin: Mapped[str] = mapped_column(String(10), default="manual")
    state: Mapped[str] = mapped_column(String(10), default="on")
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Runbook(Base):
    """What to do when a service breaks, written by an administrator (roadmap M6).

    ``ref`` is the same reference as in ``Relation``: a connection, an app
    tile, a container or a guest. A short text in Markdown and, if wanted, a
    link to a longer guide elsewhere.
    """

    __tablename__ = "runbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(200), unique=True)
    text: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(600), default="")
    updated_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class HistoryHour(Base):
    """Hour averages, lowest and highest, folded from the minutes; kept 90 days (roadmap M4)."""

    __tablename__ = "history_hours"
    __table_args__ = (UniqueConstraint("key", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    ts: Mapped[int] = mapped_column(Integer)
    avg: Mapped[float] = mapped_column(Float)
    min: Mapped[float] = mapped_column(Float)
    max: Mapped[float] = mapped_column(Float)
    count: Mapped[int] = mapped_column(Integer)


class HistoryDay(Base):
    """Day averages, lowest and highest, folded from the hours by local midnight; kept two years."""

    __tablename__ = "history_days"
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
    #: Since when this check measures. Before it, a bar of the last 7 or 30
    #: days is unknown rather than up: a check made yesterday has not seen
    #: the month. Checks from before 0.31.0 count from the update.
    created_at: Mapped[datetime | None] = mapped_column(Utc(), nullable=True, default=utcnow)

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


class Maintenance(Base):
    """A stretch in which a connection or one app tile is expected to be away.

    Kept after it ends: the availability bars of the last 30 days draw the
    time grey instead of as an outage, and they can only do that while the
    stretch is still written down.
    """

    __tablename__ = "maintenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: One of the two: a whole connection with every card on it, or one app tile.
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    widget_id: Mapped[int | None] = mapped_column(ForeignKey("widgets.id", ondelete="CASCADE"), nullable=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(Utc())
    ends_at: Mapped[datetime] = mapped_column(Utc(), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Event(Base):
    """One line of the chronicle: something that changed, and when.

    ⚠️ No foreign keys on purpose. A card or a connection that is deleted
    keeps its past: the line still says what happened to it, under the name
    it had then. Only administrators see a line whose card is gone.
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_widget_at", "widget_id", "at"), Index("ix_events_integration_at", "integration_id", "at"))

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(Utc(), default=utcnow, index=True)
    #: ``card``, ``outage``, ``recovery``, ``maintenance``, ``version``, ``container_restarted`` ... (``chronicle.KINDS``)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    #: ok, warn, bad or info: how the line is coloured.
    level: Mapped[str] = mapped_column(String(8), default="info")
    widget_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    integration_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    board_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Whoever did it, for changes made in nexdeck and sign-ins.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: What it is about, under the name it had then.
    name: Mapped[str] = mapped_column(String(200), default="")
    before: Mapped[str] = mapped_column(String(200), default="")
    after: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(String(400), default="")


class CardRecord(Base):
    """A custom card or connection: the text its author wrote and the checked definition beside it.

    ⚠️ The text is kept word for word and is what gets edited and exported: comments in the YAML live nowhere else.
    ``definition`` is the same card as JSON in the format of this nexdeck, so reading it does not parse text again.
    """

    __tablename__ = "card_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The short name; widgets refer to a card by it, so it does not change once saved.
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    #: ``card``, and ``integration`` once own connections exist.
    kind: Mapped[str] = mapped_column(String(20), default="card")
    yaml_source: Mapped[str] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: ``local`` (written here) or ``shop``.
    origin: Mapped[str] = mapped_column(String(10), default="local")
    shop_ref: Mapped[str] = mapped_column(String(200), default="")
    shop_version: Mapped[str] = mapped_column(String(20), default="")
    #: The checksum of the text as it was installed from the shop (``workshop/install.normalised_hash``): a text that no
    #: longer has it was changed here (KARTEN-15 EC-2). Empty for a card that did not come from the shop.
    shop_hash: Mapped[str] = mapped_column(String(64), default="")
    #: Whether users may put this card on a board; administrators always may.
    users_may_place: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    #: Who saved the text last: the editor names him when somebody else saved meanwhile (KARTEN-9 EC-3).
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class OwnIntegration(Base):
    """A kind of connection somebody described (KARTEN-3): the text as written and the checked definition beside it.

    The short name is what the kind is called, ``custom:<short>``, and connections refer to it by that name: deleting
    the row leaves them in the database, and saving the same short name again brings them back.
    """

    __tablename__ = "own_integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    short: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    yaml_source: Mapped[str] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: Where it came from when it was installed from the Card shop: the entry, its version and the checksum of the text then.
    shop_ref: Mapped[str] = mapped_column(String(200), default="")
    shop_version: Mapped[str] = mapped_column(String(20), default="")
    shop_hash: Mapped[str] = mapped_column(String(64), default="")


class GithubLogin(Base):
    """The GitHub sign-in of one administrator, which lets nexdeck open issues in the Workshop in his name (KARTEN-16).

    ⚠️ The tokens are encrypted under a context of this account (``workshop/github_login.py``), like the secrets of a
    connection, and the row goes with the account (``ON DELETE CASCADE``): no sign-in outlives the person it belongs to.
    """

    __tablename__ = "github_logins"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    #: The number GitHub gives the account: what owns an entry of the Workshop, so it is what is compared.
    github_id: Mapped[str] = mapped_column(String(20))
    login: Mapped[str] = mapped_column(String(100))
    access: Mapped[str] = mapped_column(Text, default="")
    refresh: Mapped[str] = mapped_column(Text, default="")
    #: When the access token stops working (about eight hours); empty when GitHub gave it no end.
    access_until: Mapped[datetime | None] = mapped_column(Utc(), nullable=True)
    #: When the sign-in ends for good (at most six months after it was made); after that the person signs in again.
    until: Mapped[datetime] = mapped_column(Utc())
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Conversation(Base):
    """A conversation with the assistant (roadmap M3), kept 30 days after its last turn."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: The first question, shortened: what the list of conversations shows.
    title: Mapped[str] = mapped_column(String(200), default="")
    #: What the person allowed in this conversation, such as reading one container's log.
    grants: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow, index=True)


class ConversationTurn(Base):
    """One entry of a conversation: a question, an answer, tool calls and their results.

    ``content`` is nexdeck's own shape, the same for every provider; ``raw``
    keeps what the provider answered, so a reply with thinking in it goes back
    to the same provider exactly as it came.
    """

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    #: ``user``, ``assistant``, ``tool``, or ``answer``: what the chat showed, with its chips and buttons.
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(20), default="")
    raw: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class ConversationDraft(Base):
    """A card the assistant drafted in a conversation (KARTEN-18): kept as long as the conversation, opened in the editor by its number.

    ``yaml`` carries invented example answers under ``demo``, made from the real ones here, so the chat can draw a small preview.
    """

    __tablename__ = "conversation_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    yaml: Mapped[str] = mapped_column(Text, default="")
    #: What the card uses (connection kind, path, form, buttons) and what went to the provider (values or not).
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sent: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


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
    #: The file's own fingerprint, so uploading the same picture twice does not
    #: make two files that both count against the quota.
    digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(Utc(), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
