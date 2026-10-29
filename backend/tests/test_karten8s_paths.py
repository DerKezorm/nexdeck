"""S4 (security review, stage 8): the path guard reads a path the way the most lenient server does.

Decoded until it stays the same (three rounds at most), with ``%u`` and overlong UTF-8, and normalised by NFKC: when that
gives ``..``, something that stands in for a dot or a control character, the path is refused. The same for the value of
a button that goes into its path.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.jsonapi import join_path
from app.cards import buttons
from app.cards.schema import lenient_reading, stays_underneath

BASE = "http://svc.example.com:8989/sub"

#: The probe of the review: spellings that must never reach the service as they are.
TRICKS = [
    "//evil.example.com/x", "/\\evil.example.com", "/@evil.example.com", "/x/../../y", "/x/%2e%2e/y", "/x/%2E%2E/y",
    "/x/.%2e/y", "/x/%252e%252e/y", "/x/..;/y", "/x/%2f..%2fy", "/x/%5c..%5cy", "/x/..\t/y", "/x/\r\nHost: evil", "/x/.",
    "/x/%00/../y", "http://evil.example.com/", "/x/%c0%ae%c0%ae/y", "/x/%u002e%u002e/y", "/x/．．/y",
    "/x/‥/y", "/x?y=1#/../../z", "/x#@evil.example.com", "/:80@evil.example.com/", "/x/%2e%2e%3f/y",
]


@pytest.mark.parametrize("path", TRICKS)
def test_karten8s_s4_the_probe_of_the_review_no_trick_reaches_the_service(path: str) -> None:
    """The probe as it was written: a path that passes must keep host, port and prefix and carry no dot in disguise."""
    if not stays_underneath(path):
        return
    url = httpx.URL(join_path(BASE, path))
    assert (url.scheme, url.host, url.port) == ("http", "svc.example.com", 8989), (path, str(url))
    assert url.raw_path.startswith(b"/sub/"), (path, url.raw_path)
    lowered = url.raw_path.split(b"?", 1)[0].lower()
    for dot in (b"/../", b"%2e%2e", b"%c0%ae", b"%u002e", b"%ef%bc%8e%ef%bc%8e", b"%e2%80%a5"):
        assert dot not in lowered + b"/", (path, url.raw_path)


@pytest.mark.parametrize(
    "path",
    [
        "/x/%c0%ae%c0%ae/y", "/x/%C0%AE./y", "/x/%e0%80%ae%e0%80%ae/y", "/x/%u002e%u002e/y", "/x/%U002E./y", "/x/．．/y",
        "/x/．/y", "/x/‥/y", "/x/․/y", "/x/﹒﹒/y", "/x/%EF%BC%8E%EF%BC%8E/y", "/x/%e2%80%a5/y", "/x/%2e%2e%3f/y",
        "/x/%c2%85/y", "/x/%7f/y", "/x/a..b", "/x/%u0000/y",
    ],
)
def test_karten8s_s4_a_dot_in_disguise_and_a_control_character_are_refused(path: str) -> None:
    assert not stays_underneath(path)


@pytest.mark.parametrize(
    "path",
    ["/api/v3/queue?page=1", "/api/Caf%C3%A9/x", "/api/Café", "/a/b.c/d", "/a/v1.2.3/x", "/a/%20b", "/a/b?x=../c", "/a/%E4%B8%AD"],
)
def test_karten8s_s4_ordinary_paths_still_pass(path: str) -> None:
    assert stays_underneath(path)


def test_karten8s_s4_decoding_stops_after_three_rounds_and_reads_the_wide_and_the_overlong_forms() -> None:
    assert lenient_reading("%c0%ae") == "."
    assert lenient_reading("%u002e") == "."
    assert lenient_reading("%2541") == "A"
    assert lenient_reading("%25252541") == "%41", "three rounds at most"
    assert lenient_reading("．") is None and lenient_reading("a\x01") is None
    assert lenient_reading("ｆｕｌｌ") == "full"


@pytest.mark.parametrize("value", ["．．", "‥", "．", "a‥b", "x\x85"])
def test_karten8s_s4_a_value_of_a_button_that_stands_in_for_a_dot_does_not_go_into_its_path(value: str) -> None:
    assert not buttons.fits_an_address(value)


@pytest.mark.parametrize("value", ["abc", 42, "Café", "v1.2", "中文"])
def test_karten8s_s4_ordinary_values_of_a_button_still_do(value: object) -> None:
    assert buttons.fits_an_address(value)
