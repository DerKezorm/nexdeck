"""What a custom card may say.

One set of models is the only source: the checks on saving, the JSON schema the
editor and the YAML completion read, and what the assistant is told. Nothing
here runs; a definition is data.

A card is a header (who, which version, what it needs), up to five requests to
the service, a form (``value``, ``stats``, ``list`` or ``posters``) that says
which parts of the answers to show, rules that colour it, and demo answers.

Texts are a string or ``{en: ..., de: ...}``. Whoever views the card gets
their own language, otherwise English, otherwise the first one written. Texts
that stand in a definition are the author's own and are never translated by
nexdeck (KARTEN-1 AC-5, AC-6).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

#: The format of the definition this nexdeck writes. A higher one is refused, a lower one is read and carried over.
FORMAT_VERSION = 1
#: A definition with its demo answers, in characters (a GitHub issue holds a little more).
MAX_DEFINITION = 60_000
NAME_MAX = 60
LABEL_MAX = 40
DESCRIPTION_MAX = 2_000
#: What a list or a poster wall shows; calculating goes over all rows, showing stops here.
MAX_ROWS = 50
DEFAULT_ROWS = 10

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
VERSION = re.compile(r"^\d{1,4}(\.\d{1,4}){0,2}$")

# -- texts -------------------------------------------------------------------

LangCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")]


def _strip(value: Any) -> Any:
    """Spaces at the edges go (KARTEN-1 EC-7)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {(key.strip() if isinstance(key, str) else key): (text.strip() if isinstance(text, str) else text) for key, text in value.items()}
    return value


def texts_of(value: str | dict[str, str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value.values())


def _limited(limit: int, *, blank_ok: bool) -> Any:
    def check(value: str | dict[str, str]) -> str | dict[str, str]:
        found = texts_of(value)
        if not blank_ok and (not found or not any(found)):
            raise PydanticCustomError("card_blank", "This must not be empty.")
        for text in found:
            if len(text) > limit:
                raise PydanticCustomError(
                    "card_too_long", "This is {length} characters long, the limit is {limit}.", {"length": len(text), "limit": limit}
                )
        return value

    return AfterValidator(check)


def _text_schema(limit: int) -> dict[str, Any]:
    text = {"type": "string", "maxLength": limit}
    return {
        "anyOf": [text, {"type": "object", "propertyNames": {"pattern": r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$"}, "additionalProperties": text}],
        "description": "A text, or one text per language such as {en: Queue, de: Warteschlange}. English is the fallback.",
    }


def _local_text(limit: int, *, blank_ok: bool = True) -> Any:
    return Annotated[
        str | dict[LangCode, str],
        BeforeValidator(_strip),
        _limited(limit, blank_ok=blank_ok),
        WithJsonSchema(_text_schema(limit)),
    ]


#: Name of a card, 60 characters; never empty.
Name = _local_text(NAME_MAX, blank_ok=False)
#: A label, a unit, a heading: 40 characters.
Label = _local_text(LABEL_MAX)
Description = _local_text(DESCRIPTION_MAX)
LocalText = str | dict[str, str]

Status = Literal["ok", "warn", "bad"]
#: ``starts_with`` and ``ends_with`` compare as text, letter case counts (``light.`` finds ``light.kitchen``).
Operator = Literal["==", "!=", ">", ">=", "<", "<=", "contains", "starts_with", "ends_with"]
#: The comparisons that look at text only. What they are compared with stays the text it was written as.
TEXT_OPERATORS = ("contains", "starts_with", "ends_with")
Shape = Literal["text", "number", "bytes", "rate", "duration", "ago", "percent", "date", "datetime", "time"]
Aggregation = Literal["count", "sum", "min", "max", "avg"]
Scalar = str | int | float | bool


def _text_only(value: Any) -> Any:
    """A version like 1.10 typed bare is a number to YAML and the zero is gone; whole numbers are fine."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        raise PydanticCustomError("card_quote_it", "Write this in quotes so that nothing is lost, for example \"{shown}\".", {"shown": str(value)})
    return value


def _text_for_text_operator(operator: Any, value: Any) -> Any:
    """``007`` stays ``007`` with ``starts_with``, ``ends_with`` and ``contains``.

    A whole number written bare comes in as text (``7`` for ``007`` is already gone in YAML, nothing to be done). A
    number with a point cannot be given back as it was written (``1.50`` reads as ``1.5``), so it is refused with the
    advice to put it in quotes, the way a version is.
    """
    if operator not in TEXT_OPERATORS or value is None or isinstance(value, bool):
        return value
    return _text_only(value)


class Part(BaseModel):
    """Every model refuses a field it does not know: a typo must not pass quietly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# -- reading the answers -----------------------------------------------------


class Filter(Part):
    """Keep the rows whose ``field`` stands in this relation to ``value``."""

    field: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    op: Operator
    value: Scalar | None = None

    @field_validator("value")
    @classmethod
    def _text_to_compare_as_text(cls, value: Any, info: ValidationInfo) -> Any:
        return _text_for_text_operator(info.data.get("op"), value)


class Sort(Part):
    field: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    desc: bool = False


class Rows(Part):
    """A list in an answer: where it is, which rows, in which order, how many are shown."""

    select: Annotated[str, StringConstraints(min_length=1, max_length=500)] = Field(
        description="A JMESPath expression that gives the list, such as records or data.items[?active]."
    )
    filter: list[Filter] = Field(default_factory=list, max_length=10)
    sort: Sort | None = None
    limit: int | None = Field(default=None, ge=1, le=MAX_ROWS, description="How many rows are shown, at most 50. Totals count all rows.")


class Rule(Part):
    """When [value] [op] [than], the colour is [then]. Without a value of its own it looks at the value it belongs to."""

    value: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, description="A path to what is compared; left out, the value the rule belongs to."
    )
    formula: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    op: Operator
    than: Scalar
    then: Status

    @field_validator("than")
    @classmethod
    def _text_to_compare_as_text(cls, value: Any, info: ValidationInfo) -> Any:
        return _text_for_text_operator(info.data.get("op"), value)

    @model_validator(mode="after")
    def _one_subject(self) -> Rule:
        if self.value is not None and self.formula is not None:
            raise PydanticCustomError("card_at_most_one", "Give at most one of {names}.", {"names": "value, formula"})
        return self


class Total(Part):
    """Count, add up or average a column of a list."""

    fn: Aggregation
    rows: Rows
    field: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = Field(
        default=None, description="The column, a path inside one row. Counting needs none."
    )

    @model_validator(mode="after")
    def _needs_a_column(self) -> Total:
        if self.fn != "count" and self.field is None:
            raise PydanticCustomError("card_needs_field", "{fn} needs a field to work on.", {"fn": self.fn})
        if self.rows.limit is not None:
            raise PydanticCustomError("card_total_limit", "A total counts all rows; leave the limit out.")
        return self


def _shorthand(value: Any) -> Any:
    """A bare string is a path: ``value: queue.total`` means ``value: {path: queue.total}``."""
    return {"path": value} if isinstance(value, str) else value


class Val(Part):
    """One value on the card: where it comes from, how it is shown and when it changes colour.

    Exactly one of ``path``, ``formula``, ``template`` and ``total``.
    """

    path: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, description="A JMESPath expression, such as records[0].title. Names with spaces go in double quotes."
    )
    formula: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, description="A calculation such as {disk.used} / {disk.total} * 100."
    )
    template: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, description="A text with values in braces, such as S{seasonNumber}E{episodeNumber}."
    )
    total: Total | None = None
    label: Label | None = None
    unit: Label | None = None
    format: Shape | None = Field(default=None, description="How to show it. Bytes, rate and duration take bytes, bytes per second and seconds.")
    digits: int | None = Field(default=None, ge=0, le=6)
    rules: list[Rule] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _one_source(self) -> Val:
        given = [name for name in ("path", "formula", "template", "total") if getattr(self, name) is not None]
        if len(given) != 1:
            raise PydanticCustomError(
                "card_one_of", "Give exactly one of {names}.", {"names": "path, formula, template, total"}
            )
        return self


#: A value, or just its path as a string.
ValueRef = Annotated[Val, BeforeValidator(_shorthand, json_schema_input_type=Val | str)]


# -- the header ----------------------------------------------------------------


class Size(Part):
    w: int = Field(ge=1, le=24)
    h: int = Field(ge=1, le=24)


def stays_underneath(path: str) -> bool:
    """A path that begins with a single /, names no host and climbs nowhere (KARTEN-2 AC-4).

    ⚠️ A segment ``..`` is refused in every spelling: the service would resolve it above the path the author wrote,
    and the connection's credentials go with it.
    """
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(c.isspace() or ord(c) < 32 for c in path):
        return False
    before_query = path.split("?", 1)[0]
    # ⚠️ ``;`` starts a path parameter (``/a/..;/b`` is ``..`` behind Tomcat), an encoded slash or backslash is a slash
    # behind nginx or Tomcat, and ``%25`` is a percent sign that is decoded twice (``%252e%252e``). None of them names a
    # real path of a service (found in the review of KARTEN-2, 25.10.2026).
    lowered = before_query.lower()
    if ";" in lowered or any(coded in lowered for coded in ("%2f", "%5c", "%25")):
        return False
    return not any(segment.replace("%2e", ".") == ".." for segment in lowered.split("/"))


class Request(Part):
    """One request to the service, always a GET underneath the address of the connection."""

    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,29}$")]
    path: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    every: Annotated[str, StringConstraints(pattern=r"^\d{1,5}[smh]$")] | None = Field(
        default=None, description="How often, such as 30s, 5m or 1h. At least 10 seconds."
    )

    @field_validator("path")
    @classmethod
    def _path_stays_underneath_the_connection(cls, path: str) -> str:
        # ⚠️ Same rule as the JSON API card (``join_path``): a path that names a host would send the connection's
        # credentials to a server of the author's choosing, and a card can come from the shop.
        if not stays_underneath(path):
            raise PydanticCustomError(
                "card_bad_path", "The path must start with a single / and name no host; it is always underneath the connection's address."
            )
        return path

    @field_validator("every")
    @classmethod
    def _not_too_often(cls, every: str | None) -> str | None:
        seconds = every_seconds(every)
        if seconds is not None and not 10 <= seconds <= 86_400:
            raise PydanticCustomError("card_bad_every", "A request is made at most every 10 seconds and at least once a day.")
        return every


def every_seconds(text: str | None) -> int | None:
    """``"30s"`` -> 30. ``None`` when the card follows the interval of the board."""
    if not text:
        return None
    return int(text[:-1]) * {"s": 1, "m": 60, "h": 3600}[text[-1]]


Kind = Annotated[str, StringConstraints(pattern=r"^(custom:)?[a-z0-9][a-z0-9_-]{0,59}$")]
Version = Annotated[str, BeforeValidator(_text_only), StringConstraints(pattern=VERSION.pattern)]


class CardBase(Part):
    format: int = Field(alias="nexdeck-card", description="The version of this format. Today 1.")
    slug: Annotated[str, StringConstraints(pattern=SLUG.pattern)] = Field(
        description="The short name: lower case letters, digits and hyphens."
    )
    name: Name
    version: Version = Field(description="The version of this card, such as 1.0.0.")
    min_nexdeck: Version | None = Field(default=None, description="The oldest nexdeck that runs this card, such as 0.48.0.")
    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    description: Description | None = None
    category: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    requires: list[Kind] = Field(
        min_length=1,
        max_length=10,
        description="The connection the card needs: a kind such as sonarr, jsonapi or custom:my-service. Several mean any one of them.",
    )
    requests: list[Request] = Field(min_length=1, max_length=5)
    rules: list[Rule] = Field(default_factory=list, max_length=10, description="Colour the whole card. Each rule names what it looks at.")
    demo: dict[str, Any] = Field(default_factory=dict, description="One example answer per request id; fills the preview, the demo mode and the shop picture.")
    size: Size | None = None
    min_size: Size | None = None

    @model_validator(mode="after")
    def _ids_are_unique(self) -> CardBase:
        ids = [request.id for request in self.requests]
        if len(set(ids)) != len(ids):
            raise PydanticCustomError("card_duplicate_id", "Two requests share the id {id}.", {"id": next(i for i in ids if ids.count(i) > 1)})
        return self


class ValueCard(CardBase):
    form: Literal["value"]
    value: ValueRef


class StatsCard(CardBase):
    form: Literal["stats"]
    stats: list[ValueRef] = Field(min_length=2, max_length=6)


class ListItem(Part):
    """What one row shows. Paths here are read inside the row."""

    title: ValueRef
    subtitle: ValueRef | None = None
    value: ValueRef | None = None
    status: list[Rule] = Field(default_factory=list, max_length=10, description="Colour of the row; a rule without a value looks at the row's value.")
    link: ValueRef | None = None
    image: ValueRef | None = None


class ListCard(CardBase):
    form: Literal["list"]
    rows: Rows
    item: ListItem
    empty: Label | None = Field(default=None, description="What the card says when there are no rows. Left out, it says Nothing here.")


class PosterItem(Part):
    image: ValueRef
    title: ValueRef
    subtitle: ValueRef | None = None
    link: ValueRef | None = None


class PostersCard(CardBase):
    form: Literal["posters"]
    rows: Rows
    item: PosterItem
    empty: Label | None = Field(default=None, description="What the card says when there are no rows. Left out, it says Nothing here.")


CardDefinition = Annotated[ValueCard | StatsCard | ListCard | PostersCard, Field(discriminator="form")]
ADAPTER: TypeAdapter[ValueCard | StatsCard | ListCard | PostersCard] = TypeAdapter(CardDefinition)


def json_schema() -> dict[str, Any]:
    """The schema of a definition: the checks, the editor, the completion in the YAML view and the assistant all read this."""
    schema = ADAPTER.json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "nexdeck card"
    return schema
