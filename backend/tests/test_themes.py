"""Colour themes: the shipped ones are readable, a pasted one is checked and
told what is hard to read, and nothing else gets into the stored setting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import themes

from .conftest import CSRF, create_user, login, setup_admin

GERMAN = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "texts.de.json"


@pytest.mark.parametrize("key", list(themes.THEMES))
def test_every_shipped_theme_is_readable_in_both_brightnesses(key: str) -> None:
    theme = themes.THEMES[key]
    assert themes.weak_spots(theme) == [], f"{key} has colours below 4.5:1"
    for mode in ("dark", "light"):
        assert set(theme[mode]) == set(themes.TOKENS), f"{key} {mode} does not set every colour"
    assert themes.check(theme) == {"name": theme["name"], "dark": theme["dark"], "light": theme["light"]}


def test_the_shipped_themes_are_named_in_german_too() -> None:
    german = json.loads(GERMAN.read_text(encoding="utf-8"))["adapter"]
    missing = [theme["name"] for theme in themes.THEMES.values() if theme["name"] not in german]
    assert missing == []
    assert len(themes.THEMES) >= 7


def test_the_contrast_is_counted_the_way_wcag_counts_it() -> None:
    assert themes.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert themes.contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    grey = {"name": "Grey", "dark": {"bg": "#111111", "bg-elev": "#111111", "surface": "#111111", "text": "#444444"}}
    assert themes.weak_spots(grey) == [{"mode": "dark", "token": "text", "ratio": 1.94}]
    # Just under the line counts, and so does a card the page does not show.
    near = {"name": "Near", "light": {"bg": "#ffffff", "text": "#777777"}}
    assert [spot["ratio"] for spot in themes.weak_spots(near)] == [4.48]
    on_card = {"name": "Card", "dark": {"bg": "#000000", "surface": "#555555", "text": "#999999"}}
    assert [spot["token"] for spot in themes.weak_spots(on_card)] == ["text"]


@pytest.mark.parametrize(("incoming", "words"), [
    ("just a name", "name and the colours"),
    ({"dark": {"bg": "#000000"}}, "needs a name"),
    ({"name": "X"}, "for dark, for light"),
    ({"name": "X", "dark": {"bg": "black"}}, "#1e293b"),
    ({"name": "X", "dark": {"background": "#000000"}}, "is not a colour"),
    ({"name": "X", "light": ["#000000"]}, "mapping"),
])
def test_what_is_not_a_theme_is_said_in_words(incoming: object, words: str) -> None:
    with pytest.raises(themes.ThemeError) as failure:
        themes.check(incoming)
    assert words in str(failure.value)


def test_a_theme_may_set_one_brightness_and_some_colours() -> None:
    assert themes.check({"name": " Dusk ", "dark": {"accent": "#AABBCC"}, "extra": 1}) == {"name": "Dusk", "dark": {"accent": "#aabbcc"}}
    assert themes.check(None) is None and themes.check({}) is None


def test_an_administrator_stores_a_theme_and_everyone_reads_it_with_its_weak_spots(client: TestClient) -> None:
    setup_admin(client)
    listed = client.get("/api/v1/settings/appearance").json()
    assert listed["theme"] is None and set(listed["themes"]) == set(themes.THEMES)
    faint = {"name": "Faint", "dark": {"bg": "#101010", "bg-elev": "#101010", "surface": "#101010", "text": "#303030"}}
    stored = client.put("/api/v1/settings/appearance", json={"preset": "cyan", "theme": faint}, headers=CSRF)
    assert stored.status_code == 200, stored.text
    assert stored.json()["theme"] == faint
    assert stored.json()["weak"] == [{"mode": "dark", "token": "text", "ratio": themes.weak_spots(faint)[0]["ratio"]}]

    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get("/api/v1/settings/appearance").json()["theme"] == faint
    assert kim.put("/api/v1/settings/appearance", json={"theme": None}, headers=CSRF).status_code == 403

    refused = client.put("/api/v1/settings/appearance", json={"theme": {"name": "X", "dark": {"bg": "red"}}}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_theme"
    assert client.get("/api/v1/settings/appearance").json()["theme"] == faint, "a refused theme leaves the stored one"
    back = client.put("/api/v1/settings/appearance", json={"theme": None}, headers=CSRF).json()
    assert back["theme"] is None and back["weak"] == []
