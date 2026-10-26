"""The definition of an own connection: a service nexdeck does not know, described in a few lines (KARTEN-3).

The shape follows ``schema`` (strict, every place can be named when it is wrong) and the text is read by the same
YAML reader as a card (``load.parse``): the same limits, the same problems with their line. What a schema cannot say
(a name that is a built-in kind, a placeholder without a field, a path that climbs out of the address) is checked in
``integration``.

⚠️ A definition holds no key. Credentials reach a request only through a placeholder ``{field}`` that the person who
sets the connection up fills in; the definition says where it goes (a header, a parameter), never what it is.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .schema import Part

#: The marker that tells a definition from a card (a card has ``nexdeck-card``).
MARKER = "nexdeck"
MAX_INTEGRATIONS = 50
MAX_TEXT = 64_000
MAX_FIELDS = 12
MAX_READS = 30

SHORT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
#: A header name as the protocol writes it, and none that belongs to the request itself.
HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,59}$")
PARAM_NAME = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,60}$")
COOKIE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
LOGO_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
LOGO_UPLOAD = re.compile(r"^/api/v1/assets/\d{1,9}/[A-Za-z0-9._-]{1,120}$")
#: ``.`` and ``..`` are no name: the address of the GitHub API is built from it.
GITHUB = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9][A-Za-z0-9-]{0,38})/(?!\.{1,2}(?:\.git)?/?$)([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
#: Headers the request itself owns; a definition cannot set them.
OWN_HEADERS = frozenset({"host", "content-length", "content-type", "connection", "transfer-encoding", "accept-encoding", "cookie"})
TICKET = "ticket"

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Template = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Path = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class DefinedField(Part):
    """One thing asked when a connection of this kind is set up (the address is always asked first)."""

    name: Annotated[str, StringConstraints(pattern=FIELD_NAME.pattern)]
    type: Literal["text", "secret", "number", "switch"] = "text"
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    help: Text = ""
    placeholder: Annotated[str, StringConstraints(max_length=100)] = ""
    required: bool = False
    default: str | int | float | bool | None = None

    @model_validator(mode="after")
    def _default_fits_the_type(self) -> DefinedField:
        if self.default is None:
            return self
        wrong = (
            self.type == "secret"
            or (self.type == "switch" and not isinstance(self.default, bool))
            or (self.type == "number" and (isinstance(self.default, bool) or not isinstance(self.default, int | float)))
            or (self.type == "text" and not isinstance(self.default, str))
        )
        if wrong:
            raise PydanticCustomError("card_integration_default", "The default does not fit the type of the field (a secret has none).")
        return self


class TicketAt(Part):
    """Where the ticket of a sign-in is: a value of the JSON answer (``at`` is a JMESPath) or a cookie."""

    from_: Literal["json", "cookie"] = Field(alias="from")
    at: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    name: Annotated[str, StringConstraints(pattern=COOKIE_NAME.pattern)] | None = None

    @model_validator(mode="after")
    def _says_where(self) -> TicketAt:
        if self.from_ == "json" and not self.at:
            raise PydanticCustomError("card_integration_ticket_json", "A ticket from the JSON answer needs at: the path of the value, such as accessToken.")
        if self.from_ == "cookie" and not self.name:
            raise PydanticCustomError("card_integration_ticket_cookie", "A ticket from a cookie needs name: the name of the cookie.")
        return self


class PassOn(Part):
    """How the ticket travels with every request."""

    as_: Literal["header", "cookie", "query"] = Field(alias="as")
    header: Annotated[str, StringConstraints(pattern=HEADER_NAME.pattern)] | None = None
    value: Template | None = None
    name: Annotated[str, StringConstraints(pattern=COOKIE_NAME.pattern)] | None = None
    param: Annotated[str, StringConstraints(pattern=PARAM_NAME.pattern)] | None = None

    @model_validator(mode="after")
    def _says_how(self) -> PassOn:
        if self.as_ == "header" and not (self.header and self.value):
            raise PydanticCustomError("card_integration_pass_header", "Passing the ticket in a header needs header: and value:, such as Bearer {ticket}.")
        if self.as_ == "query" and not self.param:
            raise PydanticCustomError("card_integration_pass_query", "Passing the ticket in the address needs param: the name of the parameter.")
        if self.header and self.header.lower() in OWN_HEADERS:
            raise PydanticCustomError("card_integration_header_own", "This header belongs to the request itself and cannot be set here.")
        return self


class Session(Part):
    """Sign in once, keep the ticket, sign in again when the service says 401."""

    login: Path
    send: Literal["json", "form"] = "json"
    body: dict[Annotated[str, StringConstraints(min_length=1, max_length=60)], Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=dict, max_length=20)
    ticket: TicketAt
    pass_: PassOn = Field(alias="pass")


class Auth(Part):
    """How a request proves who asks."""

    type: Literal["none", "header", "basic", "query", "session"] = "none"
    # header
    header: Annotated[str, StringConstraints(pattern=HEADER_NAME.pattern)] | None = None
    value: Template | None = None
    # basic
    user: Template | None = None
    password: Template | None = None
    # query (with value)
    param: Annotated[str, StringConstraints(pattern=PARAM_NAME.pattern)] | None = None
    # session
    login: Path | None = None
    send: Literal["json", "form"] | None = None
    body: dict[Annotated[str, StringConstraints(min_length=1, max_length=60)], Annotated[str, StringConstraints(max_length=500)]] | None = Field(default=None, max_length=20)
    ticket: TicketAt | None = None
    pass_: PassOn | None = Field(default=None, alias="pass")

    @model_validator(mode="after")
    def _has_what_its_type_needs(self) -> Auth:
        need: dict[str, tuple[str, ...]] = {
            "none": (),
            "header": ("header", "value"),
            "basic": ("user", "password"),
            "query": ("param", "value"),
            "session": ("login", "ticket", "pass_"),
        }
        for name in need[self.type]:
            if getattr(self, name) in (None, ""):
                shown = "pass" if name == "pass_" else name
                raise PydanticCustomError("card_integration_auth_needs", "The sign-in type {type} needs {what}.", {"type": self.type, "what": shown})
        if self.header and self.header.lower() in OWN_HEADERS:
            raise PydanticCustomError("card_integration_header_own", "This header belongs to the request itself and cannot be set here.")
        return self

    def session(self) -> Session:
        assert self.login and self.ticket and self.pass_
        return Session(login=self.login, send=self.send or "json", body=self.body or {}, ticket=self.ticket, **{"pass": self.pass_})


class Read(Part):
    """One thing worth asking of the service, offered in the step that picks the data of a card."""

    path: Path
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class VersionRead(Part):
    path: Path
    at: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class IntegrationDefinition(BaseModel):
    """An own connection, as written."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    nexdeck: Literal["integration"]
    short: Annotated[str, StringConstraints(pattern=SHORT.pattern)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    logo: str = ""
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    category: Annotated[str, StringConstraints(pattern=r"^[a-z]{3,20}$")] = "other"
    fields: list[DefinedField] = Field(default_factory=list, max_length=MAX_FIELDS)
    auth: Auth = Field(default_factory=Auth)
    test: Path
    test_expects: Literal["json", "any"] = "any"
    reads: list[Read] = Field(default_factory=list, max_length=MAX_READS)
    # Extras (KARTEN-4): kept here, they act once that part is built.
    check: Path | None = None
    version: VersionRead | None = None
    github: str | None = None

    @field_validator("logo")
    @classmethod
    def _logo_is_a_name_or_an_upload(cls, value: str) -> str:
        if value and not (LOGO_NAME.match(value) or LOGO_UPLOAD.match(value)):
            raise PydanticCustomError(
                "card_integration_logo",
                "The logo is the name of a logo from the collection, or an image uploaded to nexdeck. A picture from the web is not allowed.",
            )
        return value

    @field_validator("github")
    @classmethod
    def _github_names_a_project(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not GITHUB.match(value.strip()):
            raise PydanticCustomError("card_integration_github", "Write the project as owner/name or as https://github.com/owner/name.")
        return value.strip()


def github_project(value: str) -> str:
    """``owner/name`` from either spelling."""
    found = GITHUB.match(value.strip())
    assert found is not None
    return f"{found.group(1)}/{found.group(2)}"


def placeholders(text: str) -> list[str]:
    """The names in ``{name}`` marks of a template, in order."""
    return [found.strip() for found in PLACEHOLDER.findall(text)]


def json_schema() -> dict[str, Any]:
    return IntegrationDefinition.model_json_schema(by_alias=True)
