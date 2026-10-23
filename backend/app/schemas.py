"""Request and response bodies of the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from .languages import Code, Pair

# -- users -------------------------------------------------------------------


class UserPublic(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    locale: str
    #: The two languages in the top bar; ``locale`` is always one of them.
    language_pair: list[str]
    theme: str
    tilt: bool = True
    start_board_id: int | None
    disabled: bool
    seen_version: str
    has_password: bool = True
    auth_kind: str = "session"
    #: Address of the profile picture, or None while there is none.
    avatar_url: str | None = None
    #: Where a password reset would go; empty while none is stored.
    email: str = ""
    #: Signed in through a provider that checks the second factor itself, while the installation asks one of
    #: everybody: this session is spared, the account's API tokens wait until it sets one up.
    keys_need_second_factor: bool = False


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class MePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    #: An empty string clears the address.
    email: str | None = Field(default=None, max_length=200)
    locale: Code | None = None
    language_pair: Pair | None = None
    theme: Literal["dark", "light", "system"] | None = None
    tilt: bool | None = None
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
    locale: Code = "en"


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "user", "guest"] | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    locale: Code | None = None


class SetupBody(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    locale: Code = "en"
    demo: bool = False
    docker_host: str = Field(default="", max_length=300)


class SetupStatus(BaseModel):
    needs_setup: bool
    version: str
    demo: bool
    providers: list[dict[str, str]] = Field(default_factory=list)
    #: Whether a forgotten password can be sent anywhere. Offering the link
    #: without a mail server would be a door that opens onto a wall.
    can_reset_password: bool = False
    #: Whether the sign-in page offers the password form to everybody. Off: only the provider buttons, and below
    #: them the small way in for an administrator.
    password_login: bool = True


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


class BoardOrder(BaseModel):
    """The slugs in the order the menu should show them."""

    slugs: list[str] = Field(default_factory=list, max_length=200)


class PageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="", max_length=80)
    #: "topology" is a network plan of one UniFi connection, "home" a surface
    #: of controls of one Home Assistant connection.
    kind: Literal["cards", "topology", "home"] = "cards"
    integration_id: int | None = None
    #: Topology only: every network device at once, or only the gateway.
    start: Literal["all", "empty"] = "all"


class PagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=80)
    position: int | None = None
    sections: list[Any] | None = None
    #: Where the side bar stands (off, left, right) and how wide it is (narrow, wide).
    #: Its cards come and go with ``POST /pages/{id}/place``.
    side_place: str | None = Field(default=None, max_length=10)
    side_width: str | None = Field(default=None, max_length=10)


class PlaceSpot(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=36)
    h: int = Field(ge=1, le=40)


class PlaceBody(BaseModel):
    """One card to the board, into a group or into the side bar, in one step."""

    widget_id: int
    into: Literal["board", "group", "side"]
    group_id: int | None = None
    #: The card it goes in front of, inside a group or the side bar; last without one.
    before: int | None = None
    #: On the board: where.
    spot: PlaceSpot | None = None
    #: Inside a group or the side bar: its size there, columns of twelve and rows.
    held_w: int | None = Field(default=None, ge=1, le=12)
    held_h: int | None = Field(default=None, ge=1, le=12)


class LayoutItem(BaseModel):
    i: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=36)
    h: int = Field(ge=1, le=40)


class GridBody(BaseModel):
    """The columns a board is arranged on; its pages are rescaled to them."""

    columns: Literal[12, 24, 36]


class TopologyLayoutBody(BaseModel):
    """Who stands where on a topology page; checked in detail by ``topology.clean_layout``."""

    placed: list[str] = Field(default_factory=list, max_length=2000)
    clients: list[str] = Field(default_factory=list, max_length=2000)
    hidden: list[str] = Field(default_factory=list, max_length=2000)
    positions: dict[str, list[float]] = Field(default_factory=dict)
    #: The version the browser was looking at, as with the card layouts.
    version: int | None = None


class HomeLayoutBody(BaseModel):
    """What stands where on a home page; checked in detail by ``home.clean_layout``."""

    elements: list[Any] = Field(default_factory=list, max_length=500)
    #: The version the browser was looking at, as with the card layouts.
    version: int | None = None


class LayoutsBody(BaseModel):
    lg: list[LayoutItem] | None = None
    md: list[LayoutItem] | None = None
    sm: list[LayoutItem] | None = None
    #: The version the browser was looking at. Left out means "do not check",
    #: which is what an older browser sends.
    version: int | None = None


class ShareBody(BaseModel):
    user_id: int | None = None
    role: Literal["admin", "user", "guest"] | None = None
    level: Literal["view", "edit", "act"] = "view"


class SecondStepBody(BaseModel):
    """The second half of a sign-in: the ticket, and a code from somewhere."""

    #: Empty when the sign-in came through OpenID Connect; the ticket is in a
    #: cookie then, because that path is a redirect and an address ends up in
    #: every proxy log.
    ticket: str = Field(default="", max_length=800)
    code: str = Field(default="", max_length=40)
    recovery_code: str = Field(default="", max_length=40)


class TwoFactorConfirm(BaseModel):
    code: str = Field(max_length=12)


class TwoFactorOff(BaseModel):
    """Turning it off needs the password again, like any other undoing.

    An account signed in through OpenID Connect has no password, so for those
    a current code from the authenticator app takes its place.
    """

    password: str = Field(default="", max_length=200)
    code: str = Field(default="", max_length=16)


class ResetRequest(BaseModel):
    #: A user name or an address; the answer is the same either way.
    username: str = Field(max_length=200)


class ResetBody(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class SharesBody(BaseModel):
    shares: list[ShareBody]


class KioskCreate(BaseModel):
    name: str = Field(default="Wall display", max_length=80)
    allow_actions: bool = False
    cycle_seconds: int = Field(default=0, ge=0, le=3600)
    dim_from: str = Field(default="", max_length=5)
    dim_to: str = Field(default="", max_length=5)
    #: Minutes without a touch until the display rests on a large clock; 0 never.
    rest_minutes: int = Field(default=0, ge=0, le=240)
    #: Days until the link stops working. 0 means it does not expire on its own.
    expires_days: int = Field(default=0, ge=0, le=3650)


class KioskSession(BaseModel):
    token: str = Field(max_length=200)


class ImportBody(BaseModel):
    yaml_text: str = Field(min_length=1, max_length=2_000_000)
    slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9-]*$")


class EditYamlBody(BaseModel):
    yaml_text: str = Field(min_length=1, max_length=2_000_000)


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
    #: ⚠️ Its own flag, because ``None`` already means "not sent". Without it
    #: an interval could be set and never taken off again: the field emptied
    #: in the browser sent nothing, and the card kept the number for good.
    clear_refresh: bool = False
    page_id: int | None = None


#: The longest note a card takes: a long shopping list, not a document.
NOTE_LIMIT = 20_000


class NoteBody(BaseModel):
    content: str = Field(max_length=NOTE_LIMIT)
    #: The text the editing started from. A save whose starting point is no
    #: longer what is stored was written over somebody else's change.
    based_on: str = Field(default="", max_length=NOTE_LIMIT)


class WidgetMove(BaseModel):
    """Cards to put on another page, of this board or of another one."""

    ids: list[int] = Field(min_length=1, max_length=300)
    page_id: int


class WidgetPreview(BaseModel):
    """Draft settings for a preview fetch. Nothing is saved."""

    options: dict[str, Any] = Field(default_factory=dict)
    integration_id: int | None = None
    clear_integration: bool = False


class HomeSwitchBody(BaseModel):
    """What a home page asks of a lamp. No service and no entity: the server finds both (``home_control``).

    Off is off and nothing else. A brightness, a white or a colour switches the
    lamp on with it; a white and a colour at once is two wishes, and refused.
    Whether the lamp can do what is asked, ``home_control.service_for`` decides.
    """

    model_config = ConfigDict(extra="forbid")

    on: StrictBool | None = None
    brightness_pct: StrictInt | None = Field(default=None, ge=1, le=100)
    #: Bounded loosely here; the lamp's own range is applied in ``home_control``.
    kelvin: StrictInt | None = Field(default=None, ge=1000, le=12000)
    #: Hue in degrees and saturation in percent, as Home Assistant's ``hs_color``.
    hs: tuple[StrictFloat, StrictFloat] | None = None

    @model_validator(mode="after")
    def _one_wish(self) -> HomeSwitchBody:
        asked = [self.brightness_pct, self.kelvin, self.hs]
        if self.on is None and all(value is None for value in asked):
            raise ValueError("Say what the lamp should do.")
        if self.on is False and any(value is not None for value in asked):
            raise ValueError("Off takes nothing with it.")
        if self.kelvin is not None and self.hs is not None:
            raise ValueError("A white or a colour, not both.")
        if self.hs is not None and not (0 <= self.hs[0] <= 360 and 0 <= self.hs[1] <= 100):
            raise ValueError("Hue goes from 0 to 360, saturation from 0 to 100.")
        return self


class HomeClimateBody(BaseModel):
    """What a home page asks of a thermostat: one thing at a time, no service and no entity (``home_control``)."""

    model_config = ConfigDict(extra="forbid")

    target: StrictFloat | None = Field(default=None, ge=-50, le=100)
    mode: str | None = Field(default=None, pattern=r"^[a-z_]{1,40}$")
    preset: str | None = Field(default=None, min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_ .-]+$")

    @model_validator(mode="after")
    def _one_wish(self) -> HomeClimateBody:
        if sum(value is not None for value in (self.target, self.mode, self.preset)) != 1:
            raise ValueError("Ask a thermostat one thing at a time: a target, a mode or a preset.")
        return self


class HomeCoverBody(BaseModel):
    """What a home page asks of a cover or a card of covers: one thing, no service and no entity (``hass_covers``).

    ``member`` picks one cover of a card by the entity id it was placed with;
    without it the card's covers all go. ``scene`` is one of the card's
    positions of its own, by its place.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["open", "close", "stop"] | None = None
    position: StrictInt | None = Field(default=None, ge=0, le=100)
    tilt: StrictInt | None = Field(default=None, ge=0, le=100)
    scene: StrictInt | None = Field(default=None, ge=0, le=5)
    member: str | None = Field(default=None, pattern=r"^cover\.[a-z0-9_]{1,200}$")

    @model_validator(mode="after")
    def _one_wish(self) -> HomeCoverBody:
        if sum(value is not None for value in (self.action, self.position, self.tilt, self.scene)) != 1:
            raise ValueError("Ask a cover one thing at a time: open, close, stop, a position, a slat angle or a position of the card.")
        return self


class HomeSceneBody(BaseModel):
    """A scene or script set off from a home page, one of a card by ``member``; ``stop`` stops a script that runs."""

    model_config = ConfigDict(extra="forbid")

    member: str | None = Field(default=None, pattern=r"^(scene|script)\.[a-z0-9_]{1,200}$")
    stop: StrictBool = False


class HomeToggleBody(BaseModel):
    """A switch or helper switched from a home page, one of a card by ``member``, or all of the card."""

    model_config = ConfigDict(extra="forbid")

    on: StrictBool
    member: str | None = Field(default=None, pattern=r"^(switch|input_boolean)\.[a-z0-9_]{1,200}$")


class ActionBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class PlaylistCreate(BaseModel):
    """A new playlist starts with the tracks it was made for: neither server was measured making an empty one."""

    name: str = Field(min_length=1, max_length=200)
    track_ids: list[str] = Field(min_length=1, max_length=500)


class PlaylistTracks(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=500)


class PlaylistEntries(BaseModel):
    #: The places in the playlist, not the tracks: the same track may stand in it twice.
    entries: list[str] = Field(min_length=1, max_length=500)


class PlaylistRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


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
    muted: bool | None = None


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
    #: Days until the token stops working. 0 means it does not expire on its own.
    expires_days: int = Field(default=0, ge=0, le=3650)


class SettingsBody(BaseModel):
    public_url: str | None = Field(default=None, max_length=300)
    update_check: bool | None = None
    demo: bool | None = None
    default_locale: Code | None = None
    #: Whether everybody has to set up a second factor before doing anything.
    require_two_factor: bool | None = None
    #: Sign-in with a password for everybody (off: administrators only; needs an active provider).
    password_login: bool | None = None
    #: The administrator answered the question about the redirect addresses that follow the public address.
    confirm_address: bool = False


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


class SearchTargetBody(BaseModel):
    """One place a typed word can be handed to."""

    name: str = Field(min_length=1, max_length=40)
    #: Has to carry ``{query}``; the service puts the words in.
    url: str = Field(min_length=1, max_length=400)
    prefix: str = Field(default="", max_length=6)
    icon: str = Field(default="", max_length=80)


class SearchBody(BaseModel):
    """The search bar's targets, in the order they are offered."""

    enabled: bool = True
    targets: list[SearchTargetBody] = Field(default_factory=list, max_length=20)


class BrandBody(BaseModel):
    """The name of the installation and where its logo stands in for nexdeck's."""

    #: Roomier than the 40 characters on purpose: a longer one gets a sentence back, not a 422.
    name: str = Field(default="", max_length=200)
    favicon: str = Field(default="logo", max_length=20)
    app_icon: str = Field(default="logo", max_length=20)
    board_in_title: Any = True


class AppearanceBody(BaseModel):
    """The accent colour of the installation, and a style sheet of its own."""

    preset: str = Field(default="cyan", max_length=20)
    #: A colour of one's own as ``#rrggbb``; empty means the preset wins.
    #: Roomier than the six digits on purpose, so anything else a person types
    #: reaches the service and gets a sentence back instead of a 422.
    accent: str = Field(default="", max_length=32)
    css: str = Field(default="", max_length=20000)
    #: A theme, ``{"name", "dark": {colour: "#rrggbb"}, "light": {...}}``, or null for nexdeck's own look.
    #: Loosely typed so that a pasted theme gets a sentence back, not a 422.
    theme: dict[str, Any] | None = None
    #: How a card is drawn: glass, liquid, flat, outline or neon.
    card_style: str = Field(default="glass", max_length=20)
    #: The corners of a card and the room between two, in pixels. Loose for the same reason as the accent.
    radius: int | None = None
    gap: int | None = None
    #: Liquid glass: whether its rim bends the background. Loose for the same reason as the accent.
    refraction: Any = True


class AppAddress(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=600)


class AppCreate(BaseModel):
    """An app for the catalog (issue #37)."""

    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=300)
    addresses: list[AppAddress] = Field(min_length=1, max_length=8)
    home: str = Field(default="", max_length=40)
    away: str = Field(default="", max_length=40)


class AppPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=300)
    addresses: list[AppAddress] | None = Field(default=None, min_length=1, max_length=8)
    home: str | None = Field(default=None, max_length=40)
    away: str | None = Field(default=None, max_length=40)
