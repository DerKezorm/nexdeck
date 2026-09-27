"""The languages the interface speaks, and the two of them in the top bar.

The frontend keeps the same list in ``frontend/src/i18n/index.ts``; a guard
test holds the two together. A code that is not on it is refused, so an
account can never be left in a language nothing can show.
"""

from __future__ import annotations

from typing import Annotated, Protocol

from pydantic import AfterValidator

SUPPORTED: tuple[str, ...] = ("en", "de", "es")

#: The two buttons in the top bar until somebody chooses others.
DEFAULT_PAIR: tuple[str, str] = ("en", "de")


def check_code(code: str) -> str:
    if code not in SUPPORTED:
        raise ValueError(f"Unknown language {code!r}; nexdeck speaks {', '.join(SUPPORTED)}.")
    return code


def check_pair(pair: list[str]) -> list[str]:
    if len(pair) != 2:
        raise ValueError("The top bar holds exactly two languages.")
    if pair[0] == pair[1]:
        raise ValueError("The two languages in the top bar have to differ.")
    return pair


Code = Annotated[str, AfterValidator(check_code)]
Pair = Annotated[list[Code], AfterValidator(check_pair)]


def read_pair(stored: str) -> list[str]:
    """The stored pair, or the default where the column holds anything else."""
    pair = stored.split(",")
    if len(pair) == 2 and pair[0] != pair[1] and all(code in SUPPORTED for code in pair):
        return pair
    return list(DEFAULT_PAIR)


def write_pair(pair: list[str]) -> str:
    return ",".join(pair)


def pair_with(pair: list[str], active: str, chosen: str) -> list[str]:
    """The pair once ``chosen`` becomes the language, coming from ``active``.

    The active language is always one of the two buttons. A language from
    outside the pair takes the place of the button that was not active, so
    the way back to the language just left stays one press away. Where the
    active language was not in the pair at all, the second button gives way.
    """
    if chosen in pair:
        return list(pair)
    keep = active if active in pair else pair[0]
    return [keep, chosen] if pair[0] == keep else [chosen, keep]


def active_after(old_pair: list[str], new_pair: list[str], active: str) -> str:
    """The language once the pair itself changes.

    It stays where it is while it is still one of the two; if its button was
    given another language, that language is the one now showing.
    """
    if active in new_pair:
        return active
    index = old_pair.index(active) if active in old_pair else 0
    return new_pair[index]


class _Speaker(Protocol):
    locale: str
    language_pair: str


def apply(user: _Speaker, locale: str | None, pair: list[str] | None) -> None:
    """Set the language, the pair, or both, and keep the one inside the other.

    The pair goes first: a request that brings both means the language within
    the new pair.
    """
    current = read_pair(user.language_pair)
    if pair is not None:
        user.locale = active_after(current, pair, user.locale)
        current = list(pair)
    if locale is not None:
        current = pair_with(current, user.locale, locale)
        user.locale = locale
    user.language_pair = write_pair(current)
