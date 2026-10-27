"""From YAML text to a checked definition of an own connection (KARTEN-3).

Read by the reader a card is read by, so every problem comes with its line. After the schema come the things a schema
cannot say: the short name is no built-in kind (EC-1), every ``{placeholder}`` has a field, every path stays underneath
the address of the connection and only reads, and no key stands in the text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from ..adapters.base import AdapterError
from . import credentials, load
from . import integration_schema as sch
from .schema import stays_underneath

Path = load.Path
Problem = load.Problem


@dataclass(frozen=True)
class LoadedIntegration:
    definition: sch.IntegrationDefinition
    #: The definition as plain JSON, what the table keeps beside the text.
    data: dict[str, Any]
    text: str
    lines: dict[Path, int] = field(default_factory=dict, repr=False)


def _from_data(data: dict[str, Any]) -> sch.IntegrationDefinition:
    return sch.IntegrationDefinition.model_validate(data)


def definition_from_data(data: dict[str, Any]) -> sch.IntegrationDefinition:
    """A definition from the JSON the table keeps."""
    return _from_data(data)


def _strings(value: Any, path: Path = ()) -> list[tuple[Path, str]]:
    if isinstance(value, str):
        return [(path, value)]
    found: list[tuple[Path, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found += _strings(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += _strings(child, (*path, index))
    return found


def _templates(definition: sch.IntegrationDefinition) -> list[tuple[Path, str, bool]]:
    """Every text that may hold ``{placeholders}``, with its place and whether ``{ticket}`` is one of them."""
    auth = definition.auth
    found: list[tuple[Path, str, bool]] = []
    for name in ("value", "user", "password"):
        text = getattr(auth, name)
        if text:
            found.append((("auth", name), text, False))
    for names, text in sch.body_texts(auth.body or {}):
        found.append((("auth", "body", *names), text, False))
    if auth.pass_ is not None and auth.pass_.value:
        found.append((("auth", "pass", "value"), auth.pass_.value, True))
    return found


def _expression(add: Any, path: Path, expression: str) -> None:
    import jmespath
    from jmespath.exceptions import JMESPathError

    try:
        jmespath.compile(expression)
    except JMESPathError as failure:
        add("card_integration_expression", f"This is not a path into the answer: {failure}.", path, reason=str(failure))


def _semantic(definition: sch.IntegrationDefinition, lines: dict[Path, int]) -> list[Problem]:
    from .. import adapters

    problems: list[Problem] = []

    def add(code: str, message: str, path: Path, **params: Any) -> None:
        problems.append(Problem(code, message, load._key_name(path), load._line(lines, path), params))

    if definition.short in adapters.builtin_kinds():
        add("card_integration_short_taken", f"nexdeck has a built-in kind called {definition.short}. Pick another short name.", ("short",), short=definition.short)
    categories = adapters.builtin_categories()
    if definition.category not in categories:
        add("card_not_allowed", f"This must be one of {', '.join(sorted(categories))}.", ("category",), expected=", ".join(sorted(categories)))
    names = [one.name for one in definition.fields]
    for index, one in enumerate(definition.fields):
        if one.name in ("url", "insecure", sch.TICKET):
            add("card_integration_field_reserved", f"The field name {one.name} is kept: the address and the TLS switch are always there.", ("fields", index, "name"), field=one.name)
        elif names.index(one.name) != index:
            add("card_duplicate_key", f"The field {one.name} stands twice.", ("fields", index, "name"), field=one.name)
    known = set(names)
    for path, text, ticket_ok in _templates(definition):
        for name in sch.placeholders(text):
            if name in known or (ticket_ok and name == sch.TICKET):
                continue
            add("card_integration_placeholder_unknown", f"{{{name}}} names no field of this connection.", path, name=name)
        stripped = sch.PLACEHOLDER.sub("", text)
        if "{" in stripped or "}" in stripped:
            add("card_integration_placeholder_broken", "A brace stands alone: a placeholder is written {name}.", path)
    auth = definition.auth
    if auth.type == "session" and auth.login and not stays_underneath(auth.login):
        add("card_integration_path", "A sign-in address is a path under the address of the connection and starts with a single /.", ("auth", "login"))
    if auth.type == "session" and auth.send == "form":
        for name, child in (auth.body or {}).items():
            if isinstance(child, dict):
                add("card_integration_body_form", f"A form has no nested names: {name} holds a mapping. Send JSON for a nested body.", ("auth", "body", name), name=name)
    if auth.type == "session" and auth.ticket is not None and auth.pass_ is not None:
        if auth.pass_.as_ == "cookie" and not (auth.pass_.name or auth.ticket.name):
            add("card_integration_pass_cookie", "Passing the ticket as a cookie needs name: the name of the cookie.", ("auth", "pass", "name"))
        if auth.ticket.from_ == "json" and auth.ticket.at:
            _expression(add, ("auth", "ticket", "at"), auth.ticket.at)
    if definition.version is not None:
        _expression(add, ("version", "at"), definition.version.at)

    def reading(path: Path, text: str | None) -> None:
        if text is None:
            return
        if not stays_underneath(text):
            add("card_integration_path", "A path starts with a single /, names no host and climbs nowhere.", path)
            return
        from ..adapters.rawread import refuse_a_command

        try:
            refuse_a_command(SimpleNamespace(raw_read_commands=None), text)  # type: ignore[arg-type]
        except AdapterError as failure:
            add("card_integration_path_acts", failure.message, path)

    if auth.type == "session" and auth.login and stays_underneath(auth.login):
        reading(("auth", "login"), auth.login)  # the one POST of a connection: no path that acts, whoever wrote the description
    reading(("test",), definition.test)
    reading(("check",), definition.check)
    if definition.version is not None:
        reading(("version", "path"), definition.version.path)
    for index, one in enumerate(definition.reads):
        reading(("reads", index, "path"), one.path)
    return problems


def load_integration(text: str) -> LoadedIntegration:
    """Read, check and return a definition, or raise ``load.CardInvalid`` with everything that is wrong."""
    data, lines = load.parse(text, sch.MAX_TEXT)
    if data.get(sch.MARKER) != "integration":
        hint = "This is a card, not a connection." if "nexdeck-card" in data else "A connection starts with nexdeck: integration."
        raise load.CardInvalid([Problem("card_integration_marker", hint, sch.MARKER, load._line(lines, (sch.MARKER,)) or 1)])
    keys = [Problem("card_secret_value", f"This looks like {credentials.PHRASES[what]}. A definition holds no secrets: write a placeholder such as {{token}} and the person who sets up the connection fills it in.", load._key_name(path), load._line(lines, path), {"what": what})
            for path, value in _strings(data)
            if (what := credentials._value(value, structure=False))]
    if keys:
        raise load.CardInvalid(keys)
    try:
        definition = _from_data(data)
    except ValidationError as failure:
        found = {(problem.path, problem.code): problem for problem in (load._from_pydantic(error, lines) for error in reversed(failure.errors()))}
        raise load.CardInvalid(list(reversed(found.values()))) from failure
    problems = _semantic(definition, lines)
    if problems:
        raise load.CardInvalid(problems)
    dumped = definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    return LoadedIntegration(definition, dumped, text, lines)


#: What a new definition starts from (shown by ``GET /own-integrations/template``).
TEMPLATE = """\
nexdeck: integration
# The name the connection is called in nexdeck, and the short name that identifies it (lower case, digits, - and _).
short: my-service
name: My service
# A logo from the collection (the name of a service) or an image uploaded to nexdeck. Optional.
logo: ""
description: What this service is, in a few words.
category: other

# What a person is asked when setting up a connection. The address is always asked first.
# type: text | secret | number | switch. A secret is stored encrypted and never shown again.
fields:
  - name: token
    type: secret
    label: Access token
    help: Where to create the token in the service.
    required: true

# How a request proves who asks. {token} is replaced by what was typed into the field of that name.
#   none
#   header:  header: Authorization    value: "Bearer {token}"
#   basic:   user: "{username}"       password: "{password}"
#   query:   param: apikey            value: "{token}"
#   session: login: /api/login  send: json  body: {username: "{username}", password: "{password}"}
#            ticket: {from: json, at: accessToken}     # or {from: cookie, name: session}
#            pass: {as: header, header: Authorization, value: "Bearer {ticket}"}   # or {as: cookie} or {as: query, param: sid}
auth:
  type: header
  header: Authorization
  value: "Bearer {token}"

# One path under the address of the connection. Green when the service answers 2xx.
test: /api/status
# Optional: json turns an answer that is no JSON (a web page) into a red result.
test_expects: any

# Optional: what is worth asking of the service, offered when a card is built.
reads:
  - path: /api/items?limit=10
    label: Latest items

# Optional extras: a path for the reachability check, where the version stands in an answer, the project on GitHub.
# check: /health
# version: {path: /api/status, at: version}
# github: owner/name
"""
