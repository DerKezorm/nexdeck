"""From the answers of a service to the finished values of a card.

Answers in, a plain ``Result`` out: the rows chosen, filtered, sorted and
limited, the values picked, calculated and formatted, the colours from the
rules. The browser never sees an expression, only what came out (KARTEN-5
AC-10), and nothing here can do more than read, compare and calculate.

The form decides what is read (``value``, ``stats``, ``list``, ``posters``);
mapping a ``Result`` onto what a card draws belongs to whoever draws the form.
"""

from __future__ import annotations

import calendar
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..adapters.base import AdapterError, ago, duration_short, human_bytes, human_rate
from . import buttons
from . import formula as calc
from .buttons import Button
from .schema import DEFAULT_ROWS, MAX_ROWS, Filter, LocalText, Rows, Rule, Sort, Total, Val

#: What a card may spend on calculating one answer, in milliseconds (KARTEN-5 AC-11).
BUDGET_MS = 50.0
#: Between two looks at the clock while going through rows.
CHECK_EVERY = 500
#: What a value shows when there is nothing to show.
NOTHING = "–"
RANK = {"ok": 0, "warn": 1, "bad": 2}
#: Named here so a test can move time; nothing else touches it.
clock = time.perf_counter


@dataclass
class Shown:
    """One finished value. ``text`` is what to show; ``value`` is what it is, for a language to format its own way."""

    value: Any
    text: str
    format: str = "text"
    digits: int | None = None
    label: LocalText | None = None
    unit: LocalText | None = None
    status: str | None = None


@dataclass
class Row:
    title: Shown
    subtitle: Shown | None = None
    value: Shown | None = None
    status: str | None = None
    link: str | None = None
    image: str | None = None
    #: The picture address is one value the answer named (a path), not something put together from a template: only
    #: then may it lead to a host other than the connection's (korrektur J1, F3).
    image_named: bool = False
    #: The buttons on this row that can be offered, by id, each with the values of this row it takes (KARTEN-8 AC-2).
    buttons: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Result:
    form: str
    status: str | None = None
    value: Shown | None = None
    stats: list[Shown] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    #: How many rows matched before the limit cut the list; totals count all of them.
    total: int = 0
    #: What the answers did not hold (a path that gave nothing), for the preview in the editor.
    missing: list[str] = field(default_factory=list)
    millis: float = 0.0
    #: The buttons on the card that can be offered, by id, each with the values of the answers it takes (KARTEN-8 AC-1).
    buttons: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self, *, for_the_editor: bool = False) -> dict[str, Any]:
        """The result as plain data. ``missing`` quotes expressions of the card, so only the editor's preview gets it."""
        data = asdict(self)
        if not for_the_editor:
            del data["missing"]
        return data


# -- compiling, once ------------------------------------------------------------------


@lru_cache(maxsize=4096)
def _ref(text: str) -> calc.Ref:
    return calc.compile_ref(text)


@lru_cache(maxsize=1024)
def _formula(text: str) -> calc.Formula:
    return calc.compile_formula(text)


@lru_cache(maxsize=1024)
def _template(text: str) -> calc.Template:
    return calc.compile_template(text)


@lru_cache(maxsize=1024)
def _getter(field: str) -> Callable[[Any], Any]:
    """How to read one field out of a row.

    A plain name is a dictionary lookup, which is what almost every field is and what keeps ten thousand rows inside
    the time a card has. Anything else (a path, a quoted name, a function) goes through JMESPath.
    """
    if calc.PLAIN_NAME.match(field):
        return lambda row: row.get(field) if isinstance(row, dict) else None
    return _ref(field).search


def _models(node: Any, path: tuple[str | int, ...] = ()) -> list[tuple[tuple[str | int, ...], BaseModel]]:
    found: list[tuple[tuple[str | int, ...], BaseModel]] = []
    if isinstance(node, list):
        for index, child in enumerate(node):
            found += _models(child, (*path, index))
    elif isinstance(node, BaseModel):
        found.append((path, node))
        for name in type(node).model_fields:
            if name != "demo":
                found += _models(getattr(node, name), (*path, name))
    return found


def expression_problems(definition: Any) -> list[tuple[tuple[str | int, ...], str, calc.FormulaError]]:
    """Every expression in a definition that cannot be read, with its place and the reason (KARTEN-5 AC-9)."""
    problems: list[tuple[tuple[str | int, ...], str, calc.FormulaError]] = []

    def check(path: tuple[str | int, ...], what: str, text: str | None, how: Any) -> None:
        if text is None:
            return
        try:
            how(text)
        except calc.FormulaError as failure:
            problems.append(((*path, what), what, failure))

    for path, model in _models(definition):
        if isinstance(model, Val):
            check(path, "path", model.path, _ref)
            check(path, "formula", model.formula, _formula)
            check(path, "template", model.template, _template)
        elif isinstance(model, Rows):
            check(path, "select", model.select, _ref)
        elif isinstance(model, Filter | Sort | Total):
            check(path, "field", model.field, _ref)
        elif isinstance(model, Button):
            check(path, "answer", model.answer, _ref)
        if isinstance(model, Rule):
            check(path, "value", model.value, _ref)
            check(path, "formula", model.formula, _formula)
    return problems


# -- running ----------------------------------------------------------------------------


class _SystemZone(tzinfo):
    """The clock of the machine, asked for every moment: July and January each get their own offset.

    Only for a system that names no zone in ``TZ``. Asking once for today's offset would make every other season wrong.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        try:
            return timedelta(seconds=_system_offset(time.mktime(dt.replace(tzinfo=None).timetuple())))
        except (OverflowError, OSError, ValueError):
            return timedelta(0)

    def fromutc(self, dt: datetime) -> datetime:
        try:
            seconds = _system_offset(calendar.timegm(dt.replace(tzinfo=None).utctimetuple()))
        except (OverflowError, OSError, ValueError):
            seconds = 0
        return (dt.replace(tzinfo=None) + timedelta(seconds=seconds)).replace(tzinfo=self)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str | None:
        return None


def _system_offset(timestamp: float) -> int:
    return time.localtime(timestamp).tm_gmtoff


def instance_zone() -> tzinfo:
    """The time zone of the instance: ``TZ`` when it names one, else the clock of the machine, else UTC (KARTEN-5 EC-5, EC-9).

    Not the offset of today: a card that shows a July time in January with the January offset is an hour wrong.
    """
    named = os.environ.get("TZ", "").strip().lstrip(":")
    if named:
        try:
            return ZoneInfo(named)
        except (ValueError, OSError, KeyError):
            pass
    try:
        _system_offset(0)
    except (OverflowError, OSError, ValueError, AttributeError):
        return UTC
    return _SystemZone()


class _Budget:

    def __init__(self, milliseconds: float) -> None:
        self.start = clock()
        self.limit = milliseconds

    def spent(self) -> float:
        return (clock() - self.start) * 1000

    def check(self) -> None:
        if self.spent() > self.limit:
            raise AdapterError(
                "The calculation took too long.",
                code="too_slow",
                hint="Choose fewer values or filter the rows before they are counted.",
            )


class _Run:
    def __init__(self, answers: dict[str, Any], tz: tzinfo | None, now: float | None, budget: _Budget) -> None:
        self.answers = answers
        # A card that reads one request may leave the request's name out of its paths (``records[0]``, not ``queue.records[0]``).
        self.single = next(iter(answers)) if len(answers) == 1 else None
        self.tz = tz or instance_zone()
        self.now = now if now is not None else time.time()
        self.budget = budget
        self.missing: dict[str, None] = {}
        #: What a path found in the answers (not inside a row), and which rows a list came to: asked once per fetch.
        self.found: dict[str, Any] = {}
        self.listed: dict[str, list[Any]] = {}

    def note_missing(self, what: str) -> None:
        if len(self.missing) < 20:
            self.missing.setdefault(what, None)

    def place(self, path: str) -> tuple[bool, Any]:
        """A placeholder of a button on the card, looked up the way a path of the card is (``search``), and whether it is there."""
        if self.single is not None:
            answer = self.answers[self.single]
            found = buttons.walk(answer, path)
            return found if found[0] else buttons.walk({self.single: answer}, path)
        return buttons.walk(self.answers, path)

    def search(self, ref: calc.Ref, row: Any = None, inside_row: bool = False) -> Any:
        """Look a path up in the answers, or inside the row when there is one.

        The clock is looked at before every look-up (KARTEN-5 AC-11), and a path asked for twice is looked up once.
        """
        self.budget.check()
        if inside_row:
            return ref.search(row)
        if ref.expression in self.found:
            return self.found[ref.expression]
        if self.single is not None:
            answer = self.answers[self.single]
            found = ref.search(answer)
            found = found if found is not None else ref.search({self.single: answer})
        else:
            found = ref.search(self.answers)
        self.found[ref.expression] = found
        return found


def _scalar(raw: Any) -> Any:
    """A list or an object is not a value to show."""
    return None if isinstance(raw, list | dict) else raw


def _natural(number: float, digits: int | None) -> str:
    if digits is not None:
        return f"{number:.{digits}f}"
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def moment(raw: Any, tz: tzinfo) -> datetime | None:
    """A point in time from an ISO text or from Unix seconds or milliseconds (KARTEN-5 EC-5, EC-8).

    A time without a zone is on the clock of the instance. ``fold`` stays 0, so a moment that happened twice on the
    night the clocks go back is read as the first of them.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    number = calc.as_number(raw)
    try:
        if number is not None:
            # Past 1e11 a count of seconds would be the year 5138; it is milliseconds.
            return datetime.fromtimestamp(number / 1000 if abs(number) >= 1e11 else number, UTC)
        if isinstance(raw, str):
            parsed = datetime.fromisoformat(raw.strip())
            return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _format(run: _Run, raw: Any, shape: str | None, digits: int | None) -> tuple[Any, str, str]:
    """(value, text, format) of a raw value in a shape. Nothing to show gives ``(None, "–", shape)``."""
    shape = shape or "text"
    if raw is None:
        return None, NOTHING, shape
    if shape == "text":
        # ⚠️ A text stays exactly as it came, even when it reads like a number: "007" and "1.50" are names here, and
        # turning them into 7 and 1.5 would change what the author wrote. Totals, rules and the shapes below do read it as a number.
        text = calc.plain_text(raw)
        return (raw, text, shape) if text is not None else (None, NOTHING, shape)
    if shape in ("date", "datetime", "time", "ago"):
        when = moment(raw, run.tz)
        if when is None:
            return None, NOTHING, shape
        iso = when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        local = when.astimezone(run.tz)
        if shape == "ago":
            text = ago(iso, run.now)
        else:
            text = local.strftime({"date": "%Y-%m-%d", "datetime": "%Y-%m-%d %H:%M", "time": "%H:%M"}[shape])
        return iso, text or NOTHING, shape
    number = calc.as_number(raw)
    if number is None:
        return None, NOTHING, shape
    if shape == "bytes":
        return number, human_bytes(number), shape
    if shape == "rate":
        return number, human_rate(number), shape
    if shape == "duration":
        return number, duration_short(number), shape
    text = _natural(number, digits)
    return number, f"{text}%" if shape == "percent" else text, shape


def _text(value: Any) -> str:
    """A value as the text it is compared as: ``true`` and ``false`` as a card's author writes them, the rest as Python prints it."""
    return str(value).lower() if isinstance(value, bool) else str(value)


def _compare(op: str, left: Any, right: Any, right_number: float | None = None) -> bool:
    """The relation of two values. Numbers compare as numbers, also from text; everything else as text.

    ``right_number`` is the right side read as a number, for a caller that compares many rows with one value and
    would otherwise read it again every time.
    """
    if op in ("starts_with", "ends_with"):
        # Always as text, numbers too: 2026 starts with 20, 21.5 starts with 21, and "007" is not "7". A list or an
        # object starts with nothing.
        if left is None or right is None or isinstance(left, list | dict):
            return False
        return _text(left).startswith(_text(right)) if op == "starts_with" else _text(left).endswith(_text(right))
    if op == "contains":
        if isinstance(left, list):
            return any(_text(item) == _text(right) for item in left)
        return left is not None and _text(right) in _text(left)
    if isinstance(left, bool) or isinstance(right, bool):
        return (_text(left) == _text(right)) if op == "==" else (_text(left) != _text(right)) if op == "!=" else False
    if right_number is None:
        right_number = calc.as_number(right)
    # Only a right side that is a number can make the left one count as a number; a word is compared as a word.
    left_number = calc.as_number(left) if right_number is not None else None
    if left_number is not None and right_number is not None:
        pair: tuple[Any, Any] = (left_number, right_number)
    elif op in ("==", "!="):
        pair = (left, right) if left is None or right is None else (str(left), str(right))
    else:
        return False
    return {"==": pair[0] == pair[1], "!=": pair[0] != pair[1], ">": pair[0] > pair[1], ">=": pair[0] >= pair[1], "<": pair[0] < pair[1], "<=": pair[0] <= pair[1]}[op]


def _worst(statuses: list[str]) -> str | None:
    return max(statuses, key=RANK.__getitem__) if statuses else None


def _status(run: _Run, rules: list[Rule], own: Any, row: Any = None, inside_row: bool = False) -> str | None:
    """The worst colour among the rules that apply (KARTEN-5 AC-7, AC-8).

    A rule looks at what it names, else at the value it belongs to. When there is nothing to look at, the rule is silent:
    a missing field never turns a card yellow or red (EC-1).
    """
    hits: list[str] = []
    for rule in rules:
        if rule.value is not None:
            subject = run.search(_ref(rule.value), row, inside_row)
        elif rule.formula is not None:
            subject = calc.evaluate(_formula(rule.formula), lambda ref: run.search(ref, row, inside_row))
        else:
            subject = own
        if subject is None or isinstance(subject, list | dict):
            continue
        if _compare(rule.op, subject, rule.than):
            hits.append(rule.then)
    return _worst(hits)


def _row_matches(row: Any, filters: list[Filter], numbers: list[float | None]) -> bool:
    for one, number in zip(filters, numbers, strict=True):
        left = _getter(one.field)(row)
        if isinstance(left, list | dict):
            return False
        if left is None:
            # A row without the field is "not equal" to anything and fails every other test.
            if one.op != "!=" or one.value is None:
                return False
        elif number is None and type(left) is str and type(one.value) is str and one.op in ("==", "!="):
            # The common case, a word against a word, without the detour through numbers.
            if (left == one.value) != (one.op == "=="):
                return False
        elif not _compare(one.op, left, one.value, number):
            return False
    return True


def _rows_of(run: _Run, rows: Rows) -> list[Any]:
    """The rows of a list after filtering and sorting, all of them: showing the first few is up to the caller."""
    key = rows.model_dump_json(exclude={"limit"})
    if key not in run.listed:
        run.listed[key] = _rows_worked_out(run, rows)
    return run.listed[key]


def _rows_worked_out(run: _Run, rows: Rows) -> list[Any]:
    raw = run.search(_ref(rows.select))
    if not isinstance(raw, list):
        run.note_missing(rows.select)
        return []
    kept: list[Any] = []
    numbers = [calc.as_number(one.value) for one in rows.filter]
    for index, row in enumerate(raw):
        if index % CHECK_EVERY == 0:
            run.budget.check()
        if _row_matches(row, rows.filter, numbers):
            kept.append(row)
    if rows.sort is None:
        return kept
    field = _getter(rows.sort.field)
    keyed: dict[int, tuple[int, Any]] = {}
    present: list[Any] = []
    absent: list[Any] = []
    for index, row in enumerate(kept):
        if index % CHECK_EVERY == 0:
            run.budget.check()
        value = field(row)
        number = calc.as_number(value)
        if number is not None:
            keyed[id(row)] = (0, number)
        elif isinstance(value, str):
            keyed[id(row)] = (1, value.casefold())
        else:
            absent.append(row)
            continue
        present.append(row)
    present.sort(key=lambda row: keyed[id(row)], reverse=rows.sort.desc)
    return present + absent


def _total(run: _Run, total: Total) -> Any:
    rows = _rows_of(run, total.rows)
    column = _getter(total.field) if total.field else None
    if total.fn == "count":
        if column is None:
            return len(rows)
        return sum(1 for row in rows if column(row) is not None)
    numbers: list[float] = []
    for index, row in enumerate(rows):
        if index % CHECK_EVERY == 0:
            run.budget.check()
        number = calc.as_number(column(row)) if column else None
        if number is not None:
            numbers.append(number)
    if total.fn == "sum":
        return sum(numbers)
    if not numbers:
        return None
    return {"min": min, "max": max, "avg": lambda values: sum(values) / len(values)}[total.fn](numbers)


def _raw(run: _Run, val: Val, row: Any = None, inside_row: bool = False) -> Any:
    def find(ref: calc.Ref) -> Any:
        return run.search(ref, row, inside_row)

    if val.path is not None:
        return _scalar(find(_ref(val.path)))
    if val.formula is not None:
        return calc.evaluate(_formula(val.formula), find)
    if val.template is not None:
        return calc.render_template(_template(val.template), find)
    assert val.total is not None
    return _total(run, val.total)


def _value(run: _Run, val: Val, row: Any = None, inside_row: bool = False) -> Shown:
    raw = _raw(run, val, row, inside_row)
    run.budget.check()
    if raw is None:
        what = val.path or val.formula or val.template or (f"{val.total.fn} of {val.total.rows.select}" if val.total else "")
        run.note_missing(what)
    shape = val.format
    if shape is None:
        shape = "number" if isinstance(raw, int | float) and not isinstance(raw, bool) else "text"
    value, text, shape = _format(run, raw, shape, val.digits)
    return Shown(
        value=value,
        text=text,
        format=shape,
        digits=val.digits,
        label=val.label,
        unit=val.unit,
        status=_status(run, val.rules, raw if value is not None else None, row, inside_row),
    )


def _link(text: str | None) -> str | None:
    """Only an address a person may follow. What the service sent is not trusted to be one."""
    if not text:
        return None
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered.startswith(("http://", "https://")) or (stripped.startswith("/") and not stripped.startswith("//")):
        return stripped
    return None


def _row(run: _Run, item: Any, source: Any) -> Row:
    def cell(name: str) -> Shown | None:
        val = getattr(item, name, None)
        return _value(run, val, source, True) if val is not None else None

    title = cell("title")
    assert title is not None
    value = cell("value")
    link, image = cell("link"), cell("image")
    rules = getattr(item, "status", [])
    own = (value.value if value is not None else None)
    return Row(
        title=title,
        subtitle=cell("subtitle"),
        value=value,
        status=_status(run, rules, own, source, True),
        link=_link(link.text if link and link.value is not None else None),
        image=_link(image.text if image and image.value is not None else None),
        image_named=getattr(getattr(item, "image", None), "path", None) is not None,
    )


def run(
    definition: Any,
    answers: dict[str, Any],
    *,
    now: float | None = None,
    tz: tzinfo | None = None,
    budget_ms: float = BUDGET_MS,
) -> Result:
    """Everything the card shows, worked out from the answers of its requests.

    ``answers`` maps a request id to its parsed JSON. ``now`` and ``tz`` are for tests; normally it is this moment
    and the time zone of the instance. Raises ``AdapterError`` with the code ``too_slow`` past ``budget_ms``.
    """
    budget = _Budget(budget_ms)
    context = _Run(answers, tz, now, budget)
    result = Result(form=definition.form)
    if definition.form == "value":
        result.value = _value(context, definition.value)
    elif definition.form == "stats":
        result.stats = [_value(context, one) for one in definition.stats]
    else:
        everything = _rows_of(context, definition.rows)
        result.total = len(everything)
        limit = min(definition.rows.limit or DEFAULT_ROWS, MAX_ROWS)
        result.rows = [_row(context, definition.item, row) for row in everything[:limit]]
        on_rows = [one for one in definition.buttons if one.where == "row"]
        for row, source in zip(result.rows, everything[:limit], strict=True):
            for one in on_rows:
                values = buttons.offered_values(one, lambda path, source=source: buttons.walk(source, path))
                if values is not None:
                    row.buttons[one.id] = values
    for one in definition.buttons:
        if one.where == "card" and (values := buttons.offered_values(one, context.place)) is not None:
            result.buttons[one.id] = values
    result.status = _status(context, definition.rules, None)
    budget.check()
    result.missing = list(context.missing)
    result.millis = round(budget.spent(), 2)
    return result


def demo_answers(definition: Any) -> dict[str, Any] | None:
    """The example answers of a card, or ``None`` when its author gave none (the demo mode then says "no demo data")."""
    return dict(definition.demo) if definition.demo else None
