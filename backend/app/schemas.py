"""Request and response bodies of the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# -- users -------------------------------------------------------------------


class UserPublic(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    locale: str
    theme: str
    start_board_id: int | None
    disabled: bool
    seen_version: str
    has_password: bool = True
    auth_kind: str = "session"
    #: Address of the profile picture, or None while there is none.
    avatar_url: str | None = None
    #: Where a password reset would go; empty while none is stored.
    email: str = ""


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class MePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    #: An empty string clears the address.
    email: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, max_length=8)
    theme: Literal["dark", "light", "system"] | None = None
    start_board_id: int | None = None
    seen_version: str | None = Field(default=None, max_length=16)


class PasswordBody(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    role: Literal["admin", "user", "guest"] = "user"
    locale: str = Field(default="en", max_length=8)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "user", "guest"] | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    locale: str | None = Field(default=None, max_length=8)


class SetupBody(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    locale: str = Field(default="en", max_length=8)
    demo: bool = False
    docker_host: str = Field(default="", max_length=300)


class SetupStatus(BaseModel):
    needs_setup: bool
    version: str
    demo: bool
    providers: list[dict[str, str]] = Field(default_factory=list)


# -- boards ------------------------------------------------------------------


class BoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="layout-dashboard", max_length=80)
    slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9-]*$")


class BoardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=80)
    background: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    position: int | None = None
    owner_id: int | None = None
    in_menu: bool | None = None


class PageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="", max_length=80)


class PagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=80)
    position: int | None = None
    sections: list[Any] | None = None


class LayoutItem(BaseModel):
    i: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=40)


class LayoutsBody(BaseModel):
    lg: list[LayoutItem] | None = None
    md: list[LayoutItem] | None = None
    sm: list[LayoutItem] | None = None


class ShareBody(BaseModel):
    user_id: int | None = None
    role: Literal["admin", "user", "guest"] | None = None
    level: Literal["view", "edit", "act"] = "view"


class SharesBody(BaseModel):
    shares: list[ShareBody]


class KioskCreate(BaseModel):
    name: str = Field(default="Wall display", max_length=80)
    allow_actions: bool = False
    cycle_seconds: int = Field(default=0, ge=0, le=3600)
    dim_from: str = Field(default="", max_length=5)
    dim_to: str = Field(default="", max_length=5)


class ImportBody(BaseModel):
    yaml_text: str = Field(min_length=1, max_length=2_000_000)
    slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9-]*$")


# -- widgets -----------------------------------------------------------------


class WidgetCreate(BaseModel):
    kind: str = Field(min_length=3, max_length=60)
    title: str = Field(default="", max_length=120)
    icon: str = Field(default="", max_length=200)
    link: str = Field(default="", max_length=600)
    integration_id: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    refresh_seconds: int | None = Field(default=None, ge=5, le=86400)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int | None = Field(default=None, ge=1, le=40)


class WidgetPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    icon: str | None = Field(default=None, max_length=200)
    link: str | None = Field(default=None, max_length=600)
    integration_id: int | None = None
    clear_integration: bool = False
    options: dict[str, Any] | None = None
    refresh_seconds: int | None = Field(default=None, ge=5, le=86400)
    page_id: int | None = None


class WidgetPreview(BaseModel):
    """Draft settings for a preview fetch. Nothing is saved."""

    options: dict[str, Any] = Field(default_factory=dict)
    integration_id: int | None = None
    clear_integration: bool = False


class ActionBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class HealthBody(BaseModel):
    kind: Literal["http", "tcp", "ping"] = "http"
    #: Empty follows the address of the widget's integration.
    target: str = Field(default="", max_length=600)
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    expect_status: int = Field(default=0, ge=0, le=599)
    insecure: bool = False
    enabled: bool = True


# -- integrations ------------------------------------------------------------


class IntegrationCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    demo: bool = False
    admin_only: bool = False


class IntegrationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    demo: bool | None = None
    admin_only: bool | None = None


class IntegrationTest(BaseModel):
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)
    integration_id: int | None = None


# -- notifications -----------------------------------------------------------


class ChannelCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=80)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    events: list[str] = Field(default_factory=list)


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    events: list[str] | None = None


class PushSubscribeBody(BaseModel):
    subscription: dict[str, Any]


class PushUnsubscribeBody(BaseModel):
    endpoint: str


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class OidcProviderBody(BaseModel):
    slug: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    label: str = Field(min_length=1, max_length=80)
    issuer_url: str = Field(min_length=8, max_length=300)
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(default="", max_length=600)
    scopes: str = Field(default="openid profile email", max_length=200)
    enabled: bool = True
    auto_create: bool = True
    default_role: Literal["admin", "user", "guest"] = "user"


class SettingsBody(BaseModel):
    public_url: str | None = Field(default=None, max_length=300)
    update_check: bool | None = None
    demo: bool | None = None
    default_locale: str | None = Field(default=None, max_length=8)


class SmtpBody(BaseModel):
    """The installation's mail server. Sending is off while the host is empty."""

    host: str = Field(default="", max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = Field(default="", max_length=200)
    #: Left out or sent back as ``********`` keeps the stored one.
    password: str | None = Field(default=None, max_length=300)
    from_address: str = Field(default="", max_length=200)
    from_name: str = Field(default="nexdeck", max_length=120)


class MailTestBody(BaseModel):
    to_address: str = Field(default="", max_length=200)
