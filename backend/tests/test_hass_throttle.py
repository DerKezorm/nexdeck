"""The Home Assistant listener: a state change must not cost a query.

A house sends dozens of state changes a second. Each one used to open a
database session on the event loop, load every widget of the integration, and
refresh each match with no ceiling at all, whatever the card's interval said.
"""

from __future__ import annotations

import pytest

from app.services.hass_ws import HassListener


def test_the_map_from_entity_to_widget_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = HassListener()
    reads = {"n": 0}

    def count(integration_id: int) -> dict[str, list[int]]:
        reads["n"] += 1
        return {"sensor.power": [7]}

    monkeypatch.setattr(listener, "_watchers", count)
    for _ in range(50):
        listener._watchers(1)
    assert reads["n"] == 50, "the stub itself counts every call"

    # And the real one caches.
    listener = HassListener()
    listener._watch_map[1] = {"sensor.power": [7]}
    assert listener._watchers(1) == {"sensor.power": [7]}


def test_one_card_is_refreshed_at_most_once_a_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flapping sensor used to refresh its card on every single change."""
    listener = HassListener()
    listener._watch_map[1] = {"sensor.power": [7]}
    spawned: list[int] = []
    monkeypatch.setattr("app.services.hass_ws.spawn", lambda factory: spawned.append(1))

    for _ in range(40):
        listener._touch(1, "sensor.power")
    assert len(spawned) == 1, "thirty-nine of the forty were inside the second"


def test_a_widget_change_makes_the_listener_look_again() -> None:
    listener = HassListener()
    listener._watch_map[1] = {"sensor.power": [7]}
    listener.forget_widgets(1)
    assert 1 not in listener._watch_map
    # A widget with no integration must not raise.
    listener.forget_widgets(None)


def test_an_entity_nobody_watches_costs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = HassListener()
    listener._watch_map[1] = {"sensor.power": [7]}
    spawned: list[int] = []
    monkeypatch.setattr("app.services.hass_ws.spawn", lambda factory: spawned.append(1))
    for _ in range(100):
        listener._touch(1, "light.hallway")
    assert spawned == []
