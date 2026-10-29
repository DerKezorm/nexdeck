"""Skins: the file, the checker of their style sheet and what a browser is handed.

A skin is written by someone else and worn by everybody on the installation,
so most of these tests are of what is refused, each with the reason a person
reads. What passes is written anew from tokens, never passed through.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.skins import compile as skin_compile
from app.skins import css, sprites
from app.skins.schema import SkinFile, Sprite

FIXTURES = Path(__file__).parent / "fixtures" / "skins"
FENCE = ":where(:not([data-skin-guard], [data-skin-guard] *))"


def console() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "console.json").read_text(encoding="utf-8"))
    return data


def problems(source: str, **kwargs: Any) -> str:
    with pytest.raises(css.SkinCssError) as refused:
        css.compile_css(source, "k", **kwargs)
    return " | ".join(problem.message for problem in refused.value.problems)


# The style sheet ----------------------------------------------------------------------------------------------


def test_a_part_becomes_its_selectors_fenced_and_without_weight() -> None:
    out = css.compile_css("[data-part=button] { color: #ffffff }", "k")
    assert out == f":root[data-skin='k']:not([data-skin-guard]) :where(.btn){FENCE} {{ color: #ffffff }}"


def test_every_rule_of_a_whole_skin_is_fenced() -> None:
    """The guard is what keeps a skin off the sign-in page and a confirmation; no rule may miss it."""
    compiled = skin_compile.compile_skin(SkinFile.model_validate(console()))
    rules = [line for line in compiled.css.splitlines() if line.startswith(":root") and "--sk-sprite-" not in line]
    assert rules
    for rule in rules:
        selector = rule.split(" { ", 1)[0]
        for each in selector.split(", :root"):
            assert ":not([data-skin-guard])" in each and FENCE in each, rule


def test_states_options_and_brightness_land_where_they_mean() -> None:
    out = css.compile_css(
        "[data-part=card]:state(warn) > [data-part=card-titlebar]:hover { color: #000000 }\n"
        "[data-part=chip]:option(desk=weave):mode(light) { color: #000000 }",
        "k",
        options={"desk": ["weave", "plain"]},
    )
    first, second = out.splitlines()
    assert ":where(.card.glass:not(.card-plain)[data-status='warn'])" in first
    assert f" > :where(.card.glass:not(.card-plain) > header):hover{FENCE}" in first
    assert second.startswith(":root[data-skin='k']:not([data-skin-guard])[data-skin-o-desk='weave'][data-theme='light'] ")


def test_keyframes_get_the_skins_own_name_also_when_written_after_their_use() -> None:
    out = css.compile_css("[data-part=card]:hover { animation: hop 400ms }\n@keyframes hop { from { opacity: 1 } to { opacity: 0.5 } }", "k")
    assert "animation: sk-k-hop 400ms" in out and "@keyframes sk-k-hop" in out


def test_sprites_and_fonts_are_named_not_fetched() -> None:
    out = css.compile_css("[data-part=chip]::before { content: sprite(coin) }\n[data-part=chip] { font-family: font(pixel) }", "k", sprites=["coin"])
    assert "content: var(--sk-sprite-coin)" in out and "font-family: 'Pixelify Sans Variable'" in out
    assert "pointer-events: none" in out.splitlines()[0]


def test_a_text_that_only_looks_like_a_rule_is_written_anew() -> None:
    """Comments, odd spacing and escapes do not reach the browser; what it gets is serialised from tokens."""
    out = css.compile_css("/* </style><script> */ [data-part=chip]{ color:#000000 }", "k")
    assert "script" not in out and "/*" not in out


@pytest.mark.parametrize(("source", "reason"), [
    (".btn { color: red }", "[data-part=name]"),
    ("[data-part=nothing] { color: red }", "no part 'nothing'"),
    ("[data-part=card] + [data-part=chip] { color: red }", "[data-part=name]"),
    ("[data-part=card]:first-child { color: red }", "After a part come only"),
    ("[data-part=card]:state(nope) { color: red }", "no state 'nope'"),
    ("[data-part=chip]:option(desk=moon) { color: red }", "no option desk=moon"),
    ("[data-part=tab-bar]::before { color: red }", "not free"),
    ("[data-part=card]::marker { color: red }", "::before and ::after"),
    ("[data-part=card]::before [data-part=chip] { color: red }", "last part"),
    ("[data-part=card] { background: url(https://evil.example.com/a.png) }", "may not use"),
    (r"[data-part=card] { background: \75 rl(https://evil.example.com/a.png) }", "may not use"),
    ("[data-part=card] { background: image-set('https://evil.example.com/a.png' 1x) }", "holds text"),
    ("[data-part=chip] { background: element(#x) }", "element() is not allowed"),
    ("[data-part=chip] { color: attr(data-x) }", "attr() is not allowed"),
    ("[data-part=chip] { color: var(--anything) }", "var() reads only"),
    ("[data-part=chip] { color: red !important }", "!important"),
    ("[data-part=chip] { --nd-text: #ffffff }", "--sk-"),
    ("[data-part=chip] { --sk-sprite-coin: red }", "--sk-"),
    ("[data-part=chip] { position: fixed }", "not a property"),
    ("[data-part=chip]::before { position: fixed }", "absolute or nothing"),
    ("[data-part=chip] { position: relative }", "not a property"),
    ("[data-part=chip]::before { z-index: 99 }", "-1 to 10"),
    ("[data-part=chip] { pointer-events: auto }", "not a property"),
    ("[data-part=card] { opacity: 0.5 }", "not a property"),
    ("[data-part=dialog] { filter: invert(1) }", "not a property"),
    ("[data-part=chip] { opacity: 0.1 }", "0.3 or more"),
    ("[data-part=chip] { content: 'x' }", "not a property"),
    ("[data-part=chip]::before { content: 'far too long' }", "at most 8"),
    ("[data-part=chip] { font-family: Comic Sans }", "one font()"),
    ("[data-part=chip] { font-family: font(papyrus) }", "font() names one of nexdeck's fonts"),
    ("[data-part=chip] { background: sprite(ghost) }", "sprite() names one"),
    ("[data-part=chip] { color: sprite(coin) }", "a sprite goes into"),
    ("[data-part=chip] { font-size: 200px }", "9 and 72"),
    ("[data-part=chip]::before { width: 2000px }", "128 pixels"),
    ("[data-part=chip] { transition: color 5s }", "0 to 2000 ms"),
    ("[data-part=chip] { animation: hop 100ms infinite } @keyframes hop { from { opacity: 0 } to { opacity: 1 } }", "340 to 2000 ms"),
    ("[data-part=chip] { animation: nowhere 400ms }", "no @keyframes nowhere"),
    ("@keyframes grow { from { width: 0 } to { width: 100px } }", "a keyframe changes only"),
    ("@import 'https://evil.example.com/x.css';", "@import is not allowed"),
    (r"@\69mport 'https://evil.example.com/x.css';", "@import is not allowed"),
    ("@font-face { font-family: x; src: local(x) }", "@font-face is not allowed"),
    ("@media (prefers-color-scheme: dark) { [data-part=chip] { color: red } }", ":mode()"),
    ("@media print { [data-part=chip] { color: red } }", "@media asks only"),
    ("@media (max-width: 600px) { @media (min-width: 10px) { [data-part=chip] { color: red } } }", "@media is not allowed"),
    ("[data-part=chip] { [data-part=card] { color: red } }", "declarations"),
])
def test_what_a_skin_may_not_do_is_refused_with_its_reason(source: str, reason: str) -> None:
    assert reason in problems(source, sprites=["coin"], options={"desk": ["weave"]})


def test_every_problem_is_told_at_once_with_its_line() -> None:
    with pytest.raises(css.SkinCssError) as refused:
        css.compile_css("[data-part=chip] { color: red !important }\n\n[data-part=chip] { --nd-bg: #000000 }", "k")
    assert [problem.line for problem in refused.value.problems] == [1, 3]


def test_a_sheet_over_the_cap_is_refused() -> None:
    assert "longer than" in problems("[data-part=chip] { color: red }\n" * 1000)


def test_a_key_that_could_leave_its_quotes_is_refused() -> None:
    with pytest.raises(css.SkinCssError):
        css.compile_css("[data-part=chip] { color: red }", "k'] *, x[")


# The file -----------------------------------------------------------------------------------------------------


def test_the_example_skin_is_a_skin() -> None:
    compiled = skin_compile.compile_skin(SkinFile.model_validate(console()))
    # The tile lies on a layer of its own over nexdeck's light, which a skin cannot reach.
    assert f":where([data-desk-tile]){FENCE} {{ background-image: var(--sk-sprite-brick)" in compiled.css
    assert compiled.css.startswith("@layer retro, skin;\n@layer skin {")
    assert compiled.fonts == ["pixel"]
    assert compiled.presses == [{"part": "button", "selectors": [".btn"], "sound": "blip"}]
    assert compiled.sounds["blip"]["from"] == 520


@pytest.mark.parametrize(("change", "reason"), [
    (lambda d: d["tokens"].update(dark={"bg": "#000000"}), "every colour"),
    (lambda d: d["tokens"].update(font="papyrus"), "font"),
    (lambda d: d["sprites"]["coin"]["rows"].append("KK"), "equally long"),
    (lambda d: d["sprites"]["coin"]["rows"].__setitem__(0, "..KKZK.."), "no colour for 'Z'"),
    (lambda d: d["sprites"]["coin"]["palette"].update({".": "#000000"}), "see-through"),
    (lambda d: d["desk"].update(tile="ghost"), "no sprite ghost"),
    (lambda d: d["parts"].update(nothing={}), "no part 'nothing'"),
    (lambda d: d["parts"]["button"].update(sound="moo"), "no sound 'moo'"),
    (lambda d: d["decorations"].append({"part": "tab-bar", "anchor": "top-left", "sprite": "coin"}), "no place free"),
    (lambda d: d["options"][0].update(default="moon"), "not one of the choices"),
    (lambda d: d.update(key="Big Key"), "key"),
    (lambda d: d.update(extra=True), "extra"),
    (lambda d: d["sounds"]["blip"].update(volume=0.9), "volume"),
])
def test_a_broken_file_is_refused(change: Any, reason: str) -> None:
    data = console()
    change(data)
    with pytest.raises(ValidationError) as refused:
        SkinFile.model_validate(data)
    assert reason in str(refused.value)


def test_status_symbols_that_differ_only_in_colour_are_refused() -> None:
    data = console()
    data["sprites"]["red"] = {**data["sprites"]["coin"], "palette": {**data["sprites"]["coin"]["palette"], "Y": "#e52521"}}
    data["status"]["bad"] = "red"
    with pytest.raises(css.SkinCssError) as refused:
        skin_compile.compile_skin(SkinFile.model_validate(data))
    assert "differ only in colour" in str(refused.value)


def test_only_a_skin_nexdeck_ships_draws_with_its_own_sheet() -> None:
    data = {**console(), "native": "retro"}
    with pytest.raises(css.SkinCssError):
        skin_compile.compile_skin(SkinFile.model_validate(data))
    assert skin_compile.compile_skin(SkinFile.model_validate(data), builtin=True).native == "retro"


def test_a_skins_own_sheet_cannot_borrow_what_the_second_layer_may() -> None:
    data = {**console(), "css": "[data-part=chip] { position: relative }"}
    with pytest.raises(css.SkinCssError) as refused:
        skin_compile.compile_skin(SkinFile.model_validate(data))
    assert "position" in str(refused.value)


def test_weak_colours_are_told_not_refused() -> None:
    from app.services import themes

    palette = {name: "#777777" for name in themes.TOKENS}
    data = console()
    data["tokens"]["dark"] = palette
    compiled = skin_compile.compile_skin(SkinFile.model_validate(data))
    assert {"mode": "dark", "token": "text", "ratio": 1.0} in compiled.weak


# Sprites ------------------------------------------------------------------------------------------------------


def test_a_sprite_is_an_svg_of_runs_that_says_the_same_everywhere() -> None:
    sprite = Sprite(palette={"K": "#1a1a1a"}, rows=["KK.K"])
    assert sprites.svg(sprite).endswith(
        'shape-rendering="crispEdges"><rect x="0" y="0" width="2" height="1" fill="#1a1a1a"/>'
        '<rect x="3" y="0" width="1" height="1" fill="#1a1a1a"/></svg>'
    )
    # '#' would start a fragment and a quote would close the url("…") around it.
    assert not re.search(r"[#\"<>]", sprites.address(sprite).removeprefix("data:image/svg+xml,"))


def test_a_tinted_sprite_keeps_only_its_shape() -> None:
    assert 'fill="#000"' in sprites.svg(Sprite(palette={"K": "#ff0000"}, rows=["K"], tint=True))


# The registry -------------------------------------------------------------------------------------------------


def test_every_part_has_a_label_selectors_and_known_groups() -> None:
    data = css.registry()
    for name, part in data["parts"].items():
        assert css.KEY.match(name), name
        assert part["label"] and part["selectors"], name
        assert set(part["pseudo"]) <= {"::before", "::after"}, name
        for state, selectors in part.get("states", {}).items():
            assert css.KEY.match(state) and selectors, (name, state)
    assert set(data["container_refused"]) <= {prop for members in data["groups"].values() for prop in members}
