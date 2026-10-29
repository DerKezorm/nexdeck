"""B2 of the second security review: what the tick sends of a value never carries a credential, a host, a MAC or a key.

A value under a credential's name in any spelling is masked (also when the name itself is too odd to go along), a MAC or
a key of medium length as a whole value, and a host, an IPv6 address, a MAC or a key inside a text. Plain values stay.
"""

from __future__ import annotations

import json

import pytest

from app.cards import ai

ANSWER = {
    "config": {"X-Api-Key": "k7Hq2pLw9Z", "auth.token": "Tq81kZp0xx", "Api Key": "Mn44bb", "apiKey": "Ab12cd"},
    "device": {"mac": "3c:22:fb:01:02:03", "note": "Backup to nas.home.lan finished, peer fd00::1a2b up, card 3c:22:fb:01:02:03 seen"},
    "ref": "Xk9fP2qLm8Rt4Vw7Yz1A",
    "hexid": "a1b2c3d4e5f60718a1b2c3d4",
}
SECRETS = ("k7Hq2pLw9Z", "Tq81kZp0xx", "Mn44bb", "Ab12cd", "3c:22:fb:01:02:03", "nas.home.lan", "fd00::1a2b", "Xk9fP2qLm8Rt4Vw7Yz1A", "a1b2c3d4e5f60718a1b2c3d4")


def test_karten8t_b2_with_the_tick_no_credential_host_mac_or_key_goes_in_the_shape() -> None:
    shown = ai.shape(ANSWER, values=True)
    for secret in SECRETS:
        assert secret not in shown, secret
    assert shown.count('"***"') >= 6
    assert "Backup to example.com finished, peer 192.0.2.1 up, card 00:00:5e:00:53:01 seen" in shown


def test_karten8t_b2_the_examples_of_a_card_go_through_the_same_filter() -> None:
    cleaned = json.dumps(ai.clean(ANSWER))
    for secret in SECRETS:
        assert secret not in cleaned, secret


@pytest.mark.parametrize(("value", "sent"), [
    ("3c:22:fb:01:02:03", "00:00:5e:00:53:01"),
    ("Xk9fP2qLm8Rt4Vw7Yz1A", "***"),
    ("a1b2c3d4e5f60718a1b2c3d4", "***"),
    ("3f2a8c1e-4b5d-4e6f-8a7b-9c0d1e2f3a4b", "***"),
    ("nas.home.lan", "example.com"),
    ("fd00::1a2b", "192.0.2.1"),
    ("Backup to nas.home.lan.", "Backup to example.com."),
    ("see http://nas.home.lan:8080/queue?x=1", "see http://example.com/queue"),
])
def test_karten8t_b2_data_as_a_whole_value_or_in_a_text_is_stood_in_for(value: str, sent: str) -> None:
    assert ai.sendable(value) == sent


@pytest.mark.parametrize("value", [
    "Dune Part Two", "downloading", "12:30:45", "2026-10-29T12:30:00Z", "Movie.Name.2024.1080p.mkv", "v1.2.3", "1.0.1",
    "/data/media/films", "S01E02", "queued (3 of 7)", "e.g. this one", "Completed: 42%", "tool0", "eth0", "Node.js 20",
])
def test_karten8t_b2_plain_values_stay_as_they_are(value: str) -> None:
    assert ai.sendable(value) == value
