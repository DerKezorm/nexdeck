"""Looking for new files: the libraries card of Plex, Jellyfin and Emby.

⚠️ The rescan itself is never triggered here. It is a job on somebody's real
server, so every test below runs against recorded answers; what has and has
not been held against a live instance is written down in the adapters.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import all_adapters, get_adapter
from app.adapters.base import AdapterError, Context
from app.adapters.media_base import EVERYTHING, MediaAdapter

PLEX = "http://plex.example.com:32400"
JF = "http://jellyfin.example.com:8096"

SECTIONS = {"MediaContainer": {"Directory": [
    {"key": "7", "title": "4K films", "type": "movie"},
    {"key": "1", "title": "Films", "type": "movie"},
    {"key": "2", "title": "Series", "type": "show"},
    {"key": "", "title": "Broken", "type": "movie"},
]}}

FOLDERS = [
    {"ItemId": "a1", "Name": "4K films", "CollectionType": "movies", "RefreshStatus": "Idle"},
    {"ItemId": "b2", "Name": "Series", "CollectionType": "tvshows", "RefreshStatus": "Refreshing", "RefreshProgress": 41.5},
    {"Name": "No id at all", "RefreshStatus": "Idle"},
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _plex(config_extra: dict | None = None) -> dict:
    return {"url": PLEX, "token": "tok", **(config_extra or {})}


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------


@respx.mock
async def test_plex_lists_its_sections_with_a_button_each(ctx: Context) -> None:
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json=SECTIONS))
    data = await get_adapter("plex").fetch("libraries", _plex(), {}, ctx)

    assert [one["title"] for one in data.items] == ["4K films", "Films", "Series"], "a section without a key is not a row"
    assert [one["actions"][0].params for one in data.items] == [{"library": "7"}, {"library": "1"}, {"library": "2"}]
    assert data.actions[0].params == {"library": EVERYTHING}


@respx.mock
async def test_plex_says_nothing_rather_than_nought_about_the_size(ctx: Context) -> None:
    """⚠️ Plex gives the size of a section only in a call of its own. Five
    libraries would be five more requests for a number this card was not asked
    for, so the rows carry no number at all. An empty string, never 0: a shelf
    that reads "0 films" is a claim, and this card has not measured one."""
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json=SECTIONS))
    data = await get_adapter("plex").fetch("libraries", _plex(), {}, ctx)
    assert {one["value"] for one in data.items} == {""}
    assert len(respx.calls) == 1, "one request for the whole card"


@respx.mock
async def test_jellyfin_says_which_library_is_being_read(ctx: Context) -> None:
    """One call, and it already carries the scan state. Plex hands that out
    nowhere but its activity list."""
    respx.get(f"{JF}/Library/VirtualFolders").mock(return_value=httpx.Response(200, json=FOLDERS))
    data = await get_adapter("jellyfin").fetch("libraries", {"url": JF, "api_key": "k"}, {}, ctx)

    assert [one["title"] for one in data.items] == ["4K films", "Series"], "a folder without an id is not a row"
    assert data.items[0]["status"] == "ok" and data.items[0]["subtitle"] == "movies"
    # ⚠️ A library being read is not a fault. Red would train people to ignore red.
    assert data.items[1]["status"] == "unknown"
    assert data.items[1]["subtitle"] == "Scanning · 42%"
    assert data.items[1]["progress"] == 41.5
    assert next(row["value"] for row in data.secondary if row["label"] == "Scanning") == 1


# ---------------------------------------------------------------------------
# The action
# ---------------------------------------------------------------------------


@respx.mock
async def test_plex_asks_for_one_section(ctx: Context) -> None:
    route = respx.get(f"{PLEX}/library/sections/7/refresh").mock(return_value=httpx.Response(200))
    said = await get_adapter("plex").action("libraries", "rescan", {"library": "7"}, _plex(), {}, ctx)
    assert route.called
    assert "reading" in said.lower()


@respx.mock
async def test_plex_asks_for_everything(ctx: Context) -> None:
    route = respx.get(f"{PLEX}/library/sections/all/refresh").mock(return_value=httpx.Response(200))
    await get_adapter("plex").action("libraries", "rescan", {"library": EVERYTHING}, _plex(), {}, ctx)
    assert route.called


@respx.mock
async def test_plex_never_asks_for_the_deep_refresh(ctx: Context) -> None:
    """⚠️ ``force=1`` is Plex's rewrite of the metadata. This button is for
    "there are new files", and the two are one query parameter apart."""
    route = respx.get(f"{PLEX}/library/sections/7/refresh").mock(return_value=httpx.Response(200))
    await get_adapter("plex").action("libraries", "rescan", {"library": "7"}, _plex(), {}, ctx)
    assert "force" not in str(route.calls[0].request.url)


@respx.mock
async def test_jellyfin_refuses_to_read_one_library_because_it_cannot(ctx: Context) -> None:
    """⚠️ Measured on 08.09.2026 against live Jellyfin and Emby:
    ``POST /Items/{id}/Refresh`` answers 204 and does nothing at all. The scan
    task does not run and ``RefreshStatus`` never moves, with or without
    ``metadataRefreshMode=ValidationOnly``.

    A button labelled "Films" that quietly reads every library would be worse
    than no button, so the card offers per library only where per library
    works.
    """
    single = respx.post(f"{JF}/Items/a1/Refresh").mock(return_value=httpx.Response(204))
    everything = respx.post(f"{JF}/Library/Refresh").mock(return_value=httpx.Response(204))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("jellyfin").action("libraries", "rescan", {"library": "a1"}, {"url": JF, "api_key": "k"}, {}, ctx)
    assert refused.value.code == "whole_library_only"
    assert not single.called and not everything.called, "neither call may go out"


@respx.mock
async def test_jellyfin_offers_only_everything(ctx: Context) -> None:
    respx.get(f"{JF}/Library/VirtualFolders").mock(return_value=httpx.Response(200, json=FOLDERS))
    offered = await get_adapter("jellyfin").choices("library", {"url": JF, "api_key": "k"}, ctx)
    assert offered == [(EVERYTHING, "All libraries")]

    data = await get_adapter("jellyfin").fetch("libraries", {"url": JF, "api_key": "k"}, {}, ctx)
    assert data.items and all(not one["actions"] for one in data.items), "no row may promise a scan"
    assert [one.id for one in data.actions] == ["rescan"], "the card can still read everything"


@respx.mock
async def test_jellyfin_never_names_the_metadata_switches(ctx: Context) -> None:
    """⚠️ ``replaceAllMetadata`` and ``replaceAllImages`` default to false, and
    the call sends neither. Writing them out, even as false, would put a
    rewrite of the whole library one typo away."""
    route = respx.post(f"{JF}/Library/Refresh").mock(return_value=httpx.Response(204))
    await get_adapter("jellyfin").action("libraries", "rescan", {"library": EVERYTHING}, {"url": JF, "api_key": "k"}, {}, ctx)
    address = str(route.calls[0].request.url)
    assert "replaceAll" not in address and "etadataRefreshMode" not in address
    assert address.endswith("/Library/Refresh")


@respx.mock
async def test_jellyfin_refreshes_everything_through_its_own_address(ctx: Context) -> None:
    route = respx.post(f"{JF}/Library/Refresh").mock(return_value=httpx.Response(204))
    await get_adapter("jellyfin").action("libraries", "rescan", {"library": EVERYTHING}, {"url": JF, "api_key": "k"}, {}, ctx)
    assert route.called


@respx.mock
async def test_a_library_id_cannot_carry_a_path(ctx: Context) -> None:
    """⚠️ The id comes back from the browser with the action. Without a check
    it is a piece of an address somebody else chose, and httpx normalises
    ``..`` away before it sends."""
    with pytest.raises(AdapterError):
        await get_adapter("plex").action("libraries", "rescan", {"library": "../../users"}, _plex(), {}, ctx)


@respx.mock
async def test_a_refused_scan_is_a_message_not_a_silence(ctx: Context) -> None:
    respx.post(f"{JF}/Library/Refresh").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(AdapterError) as failed:
        await get_adapter("jellyfin").action("libraries", "rescan", {"library": EVERYTHING}, {"url": JF, "api_key": "k"}, {}, ctx)
    assert failed.value.code == "action_failed"


@respx.mock
async def test_an_action_nobody_offers_is_refused(ctx: Context) -> None:
    with pytest.raises(AdapterError) as no:
        await get_adapter("plex").action("libraries", "delete", {"library": "7"}, _plex(), {}, ctx)
    assert no.value.code == "no_such_action"


# ---------------------------------------------------------------------------
# The list a field can be filled from
# ---------------------------------------------------------------------------


@respx.mock
async def test_the_libraries_are_offered_as_choices_by_their_id(ctx: Context) -> None:
    """⚠️ The id, not the name. A library renamed to "4K & HDR" keeps its id;
    a stored name would point at nothing, and that shows up on the day a film
    is missing."""
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json=SECTIONS))
    offered = await get_adapter("plex").choices("library", _plex(), ctx)
    assert offered == [("7", "4K films"), ("1", "Films"), ("2", "Series"), (EVERYTHING, "All libraries")]


@respx.mock
async def test_a_field_nobody_asked_about_gets_nothing(ctx: Context) -> None:
    assert await get_adapter("plex").choices("colour", _plex(), ctx) == []
    assert len(respx.calls) == 0, "a field with no list must not cost a request"


# ---------------------------------------------------------------------------
# What the demo says, and a guard about demos in general
# ---------------------------------------------------------------------------


def test_the_demo_of_the_libraries_card_is_libraries() -> None:
    """⚠️ Written after the demo silently answered with the "now playing" card.
    It fell through to the last branch and produced two films where the rows
    belong: believable, wrong, and invisible to a test that only asks whether
    the demo threw."""
    seen = 0
    for adapter in all_adapters():
        if not isinstance(adapter, MediaAdapter):
            continue
        data = adapter.demo("libraries", {}, tick=5)
        seen += 1
        assert data.items, f"{adapter.kind}: no rows"
        for row in data.items:
            wanted = ["rescan"] if adapter.can_scan_one else []
            assert [one.id for one in row["actions"]] == wanted, f"{adapter.kind}: {row['title']}"
        assert [one.id for one in data.actions] == ["rescan"], "every one of them can read everything"
    assert seen >= 3, f"only {seen} media adapters walked"


def test_no_demo_answers_with_another_cards_data() -> None:
    """The general form of the same mistake.

    ⚠️ A ``demo`` is a chain of ``if widget_kind == ...`` with a fall-through
    at the end. A kind added to ``widgets`` and forgotten in ``demo`` does not
    fail: it silently returns whatever the last branch makes, and on screen
    that looks like a working card of the wrong sort.
    """
    #: ⚠️ Only cards that are *drawn* differently are compared. Two poster
    #: walls carry the same fields whatever is in them, and Jellyfin's "top"
    #: and "recently added" are exactly that: the same shape on purpose. The
    #: mistake this guard is about crosses renderers, because a fall-through
    #: lands in a branch that was written for another kind of card.
    doubles: list[str] = []
    checked = 0
    for adapter in all_adapters():
        seen: dict[tuple[str, str], str] = {}
        for widget in adapter.widgets:
            try:
                data = adapter.demo(widget.kind, {}, tick=5)
            except NotImplementedError:
                continue
            # The shape, not the numbers: a demo moves with the tick.
            shape = repr((
                sorted((data.primary or {}).keys()),
                [sorted(row.keys()) for row in data.secondary],
                [sorted(row.keys()) for row in data.items][:3],
                sorted(data.metrics),
                sorted((data.meta or {}).keys()),
            ))
            checked += 1
            for (other_renderer, other_shape), other_kind in seen.items():
                if other_shape == shape and other_renderer != widget.renderer:
                    doubles.append(
                        f"{adapter.kind}: {widget.kind} ({widget.renderer}) answers exactly like "
                        f"{other_kind} ({other_renderer})"
                    )
            seen[(widget.renderer, shape)] = widget.kind
    assert checked > 150, f"only {checked} demos walked; the guard is looking at nothing"
    assert not doubles, "demos that answer with another card's shape:\n  " + "\n  ".join(doubles)


# ---------------------------------------------------------------------------
# A button pointed at somebody else's action
# ---------------------------------------------------------------------------


def _button(**options) -> dict:
    return {"kind": "action", "service": "3", **options}


async def _resolver(ctx: Context, config: dict):
    """A stand-in for the collector's resolver, handing out one Plex."""
    plex = get_adapter("plex")

    async def resolve(integration_id: int):
        if integration_id != 3:
            raise AdapterError("no such integration", code="no_integration")
        return plex, config, ctx

    return resolve


@respx.mock
async def test_the_button_offers_exactly_the_action_it_was_given(ctx: Context) -> None:
    """⚠️ In the card's own answer, because that is what the collector checks a
    press against. A button that knew its action only from its options would be
    the one card in nexdeck that can be asked for anything."""
    data = await get_adapter("core").fetch("button", {}, _button(deed="rescan", target="7"), ctx)
    assert [one.id for one in data.actions] == ["rescan"]
    assert data.actions[0].params == {"target": "7"}


@respx.mock
async def test_a_button_with_nothing_picked_says_so_rather_than_offering_nothing(ctx: Context) -> None:
    data = await get_adapter("core").fetch("button", {}, _button(), ctx)
    assert data.actions == []
    assert data.status == "warn" and data.error


@respx.mock
async def test_the_button_runs_the_action_on_the_other_service(ctx: Context) -> None:
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json=SECTIONS))
    route = respx.get(f"{PLEX}/library/sections/7/refresh").mock(return_value=httpx.Response(200))
    ctx.resolve_integration = await _resolver(ctx, _plex())

    said = await get_adapter("core").action("button", "rescan", {"target": "7"}, {}, _button(deed="rescan", target="7"), ctx)
    assert route.called
    assert "reading" in said.lower()


@respx.mock
async def test_an_action_the_other_service_never_declared_is_refused(ctx: Context) -> None:
    """⚠️ The whole reason ``deeds`` exists. The options of a button are
    written by whoever may edit the board, so "what may be triggered" cannot
    come from them: it comes from the adapter's own declaration."""
    ctx.resolve_integration = await _resolver(ctx, _plex())
    with pytest.raises(AdapterError) as refused:
        await get_adapter("core").action("button", "delete_everything", {}, {}, _button(deed="delete_everything"), ctx)
    assert refused.value.code == "no_such_action"
    assert len(respx.calls) == 0, "a refused deed must not reach the service"


@respx.mock
async def test_a_target_that_is_not_on_the_services_own_list_is_refused(ctx: Context) -> None:
    """⚠️ Checked against the list the service hands out, not against a
    pattern. A section that is not on it either never existed or is gone."""
    respx.get(f"{PLEX}/library/sections").mock(return_value=httpx.Response(200, json=SECTIONS))
    refresh = respx.get(f"{PLEX}/library/sections/99/refresh").mock(return_value=httpx.Response(200))
    ctx.resolve_integration = await _resolver(ctx, _plex())

    with pytest.raises(AdapterError) as refused:
        await get_adapter("core").action("button", "rescan", {"target": "99"}, {}, _button(deed="rescan", target="99"), ctx)
    assert refused.value.code == "no_such_target"
    assert not refresh.called, "the scan must not have been asked for"


@respx.mock
async def test_a_button_that_opens_a_board_cannot_be_pressed_into_an_action(ctx: Context) -> None:
    ctx.resolve_integration = await _resolver(ctx, _plex())
    with pytest.raises(AdapterError) as refused:
        await get_adapter("core").action("button", "rescan", {"target": "7"}, {}, {"kind": "board", "board": "home"}, ctx)
    assert refused.value.code == "no_such_action"


@respx.mock
async def test_a_button_without_a_connection_says_which_field_is_empty(ctx: Context) -> None:
    ctx.resolve_integration = await _resolver(ctx, _plex())
    with pytest.raises(AdapterError) as refused:
        await get_adapter("core").action("button", "rescan", {}, {}, {"kind": "action", "deed": "rescan"}, ctx)
    assert refused.value.code == "no_integration"
    assert "pick" in refused.value.hint.lower()


def test_only_declared_deeds_are_reachable_from_a_button() -> None:
    """A floor under the allowlist: an adapter that declares nothing can be
    looked at from a button and not touched."""
    with_deeds = {a.kind for a in all_adapters() if a.deeds}
    assert with_deeds == {"plex", "jellyfin", "emby"}, f"unexpected: {sorted(with_deeds)}"
    for adapter in all_adapters():
        for one in adapter.deeds:
            assert adapter.widget(one.widget_kind), f"{adapter.kind}: {one.id} names no widget"


def test_every_word_a_deed_puts_on_screen_has_a_german_entry() -> None:
    """⚠️ Written after "Scan a library" stood in English in the settings sheet.

    The list a ``choices`` field draws is mostly names from the service, which
    pass through untranslated on purpose. The deeds are the exception: they are
    the adapter's own words, and the guard over adapter texts never saw them
    because they live on the class rather than in a ``Field``.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    german = json.loads((root / "frontend" / "src" / "i18n" / "texts.de.json").read_text(encoding="utf-8"))
    known = german["adapter"]
    missing, checked = [], 0
    for adapter in all_adapters():
        for one in adapter.deeds:
            for text in (one.label, one.target_label):
                if not text:
                    continue
                checked += 1
                if text not in known:
                    missing.append(f"{adapter.kind}: {text}")
    assert checked >= 2, f"only {checked} words walked; the guard is looking at nothing"
    assert not missing, f"deed words without a German entry: {missing}"


def test_the_word_for_all_libraries_is_translated() -> None:
    """The one label the media adapters add to the list themselves, next to
    the names that come from the service."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    german = json.loads((root / "frontend" / "src" / "i18n" / "texts.de.json").read_text(encoding="utf-8"))
    assert "All libraries" in german["adapter"]
