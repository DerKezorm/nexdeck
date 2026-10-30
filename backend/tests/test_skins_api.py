"""Skins through the API: who reads and who saves, the skin of the installation and of each account, and 1984.

1984 was the card style ``window`` before there were skins. A look saved then
must still be 1984 when read, and a look saved now must still be 1984 for
1.0 for one version: both directions are tested here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import migrations
from app.db import get_engine, session_factory
from app.models import Base, Setting, Skin
from app.services import appearance
from app.skins import store

from .conftest import CSRF, create_user, login, setup_admin

CONSOLE = (Path(__file__).parents[1] / "app" / "skins" / "examples" / "console.json").read_text(encoding="utf-8")
LOOK = {"preset": "cyan", "accent": "", "css": ""}


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    setup_admin(client)
    return client


@pytest.fixture
def user_client(admin_client: TestClient) -> TestClient:
    create_user(admin_client, "kim")
    plain = TestClient(admin_client.app)
    login(plain, "kim", "another-long-password")
    return plain


def save_console(client: TestClient) -> dict:
    answer = client.post("/api/v1/skins", headers=CSRF, json={"text": CONSOLE})
    assert answer.status_code == 201, answer.text
    return answer.json()


def test_everyone_signed_in_lists_the_skins_and_1984_is_always_there(user_client: TestClient) -> None:
    listed = user_client.get("/api/v1/skins").json()
    shipped = {skin["key"]: skin for skin in listed["skins"]}
    assert shipped["1984"]["origin"] == "builtin" and shipped["1984"]["native"] == "retro"
    assert [option["key"] for option in shipped["1984"]["options"]] == list(appearance.RETRO)
    assert TestClient(user_client.app).get("/api/v1/skins").status_code == 401


def test_only_an_administrator_saves_a_skin(user_client: TestClient) -> None:
    assert user_client.post("/api/v1/skins", headers=CSRF, json={"text": CONSOLE}).status_code == 403
    assert user_client.post("/api/v1/skins/check", headers=CSRF, json={"text": CONSOLE}).status_code == 403


def test_a_saved_skin_is_handed_out_compiled_and_asked_again_by_its_tag(admin_client: TestClient) -> None:
    saved = save_console(admin_client)
    assert saved["key"] == "console" and saved["origin"] == "own" and saved["wearable"]
    answer = admin_client.get("/api/v1/skins/console/compiled")
    assert answer.status_code == 200 and "--sk-sprite-coin" in answer.json()["css"]
    again = admin_client.get("/api/v1/skins/console/compiled", headers={"If-None-Match": answer.headers["ETag"]})
    assert again.status_code == 304
    assert admin_client.get("/api/v1/skins/nothing/compiled").status_code == 404


def test_checking_tells_every_problem_without_saving(admin_client: TestClient) -> None:
    broken = json.loads(CONSOLE)
    broken["css"] = "[data-part=chip] { color: red !important }\n.btn { color: red }"
    answer = admin_client.post("/api/v1/skins/check", headers=CSRF, json={"text": json.dumps(broken)}).json()
    assert answer["ok"] is False and [problem["line"] for problem in answer["problems"]] == [1, 2]
    assert admin_client.post("/api/v1/skins/check", headers=CSRF, json={"text": CONSOLE}).json()["ok"] is True
    assert admin_client.get("/api/v1/skins/console/compiled").status_code == 404, "checking stores nothing"


@pytest.mark.parametrize(("change", "code"), [
    (lambda d: d.update(key="1984"), "taken"),
    (lambda d: d.update(native="retro"), "bad_skin"),
    (lambda d: d.pop("nexdeck_skin"), "not_a_skin"),
])
def test_a_skin_that_may_not_be_saved_is_refused(change, code: str, admin_client: TestClient) -> None:
    data = json.loads(CONSOLE)
    change(data)
    answer = admin_client.post("/api/v1/skins", headers=CSRF, json={"text": json.dumps(data)})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == code


def test_the_same_key_twice_is_refused_and_a_change_keeps_its_place(admin_client: TestClient) -> None:
    save_console(admin_client)
    assert admin_client.post("/api/v1/skins", headers=CSRF, json={"text": CONSOLE}).json()["detail"]["code"] == "taken"
    changed = json.loads(CONSOLE)
    changed["name"] = "Retro console, louder"
    answer = admin_client.put("/api/v1/skins/console", headers=CSRF, json={"text": json.dumps(changed)})
    assert answer.status_code == 200 and answer.json()["name"] == "Retro console, louder"
    assert json.loads(admin_client.get("/api/v1/skins/console/file").text)["name"] == "Retro console, louder"


# The installation's skin ----------------------------------------------------------------------------------------


def test_the_installation_wears_a_skin_with_its_options(admin_client: TestClient) -> None:
    save_console(admin_client)
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {"key": "console", "options": {"desk": "plain"}}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["skin"] == {"key": "console", "options": {"desk": "plain"}}
    assert answer.json()["card_style"] == "glass"


@pytest.mark.parametrize(("skin", "code"), [
    ({"key": "nothing"}, "no_such_skin"),
    ({"key": "1984", "options": {"desk": "moon"}}, "bad_skin_choice"),
    ({"key": "1984", "options": {"weather": "fine"}}, "bad_skin_choice"),
])
def test_a_skin_that_is_not_there_is_refused_for_the_installation(skin: dict, code: str, admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": skin})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == code


def test_1984_is_still_the_card_style_window_for_the_version_before(admin_client: TestClient) -> None:
    """⚠️ 1.0 reads only card_style and retro. Saved as a skin, 1984 writes both as well."""
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {"key": "1984", "options": {"desk": "weave"}}}).json()
    assert answer["card_style"] == "window" and answer["retro"]["desk"] == "weave"
    assert answer["skin"] == {"key": "1984", "options": {"status": "symbol", "icons": "colour", "desk": "weave", "type": "titles"}}


def test_a_look_saved_the_old_way_as_window_is_the_skin_1984(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "card_style": "window", "retro": {"type": "all"}}).json()
    assert answer["skin"]["key"] == "1984" and answer["skin"]["options"]["type"] == "all"


def test_another_skin_takes_the_window_away(admin_client: TestClient) -> None:
    save_console(admin_client)
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "card_style": "window", "skin": {"key": "console"}}).json()
    assert answer["card_style"] == "glass" and answer["skin"]["key"] == "console"


def test_a_row_from_before_skins_reads_as_1984_without_being_rewritten(data_dir: Path) -> None:
    Base.metadata.create_all(get_engine())
    with session_factory()() as db:
        db.add(Setting(key=appearance.KEY, value={"card_style": "window", "retro": {"desk": "grey"}}))
        db.commit()
        assert appearance.stored(db)["skin"] == {"key": "1984", "options": {"status": "symbol", "icons": "colour", "desk": "grey", "type": "titles"}}
        assert "skin" not in db.get(Setting, appearance.KEY).value


def test_the_sign_in_page_shows_only_a_skin_nexdeck_ships(admin_client: TestClient) -> None:
    save_console(admin_client)
    admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {"key": "console"}})
    stranger = TestClient(admin_client.app)
    assert stranger.get("/api/v1/brand").json()["look"]["skin"] == {}
    admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {"key": "1984"}})
    assert stranger.get("/api/v1/brand").json()["look"]["skin"]["key"] == "1984"


def test_the_skin_everybody_wears_cannot_be_deleted(admin_client: TestClient) -> None:
    save_console(admin_client)
    admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {"key": "console"}})
    assert admin_client.delete("/api/v1/skins/console", headers=CSRF).json()["detail"]["code"] == "skin_in_use"
    admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "skin": {}})
    assert admin_client.delete("/api/v1/skins/console", headers=CSRF).status_code == 204
    assert admin_client.delete("/api/v1/skins/1984", headers=CSRF).status_code == 404


# Each account's own ---------------------------------------------------------------------------------------------


def test_an_account_wears_a_skin_of_its_own_and_switches_its_sounds(user_client: TestClient, admin_client: TestClient) -> None:
    save_console(admin_client)
    answer = user_client.patch("/api/v1/auth/me", headers=CSRF, json={"skin": {"key": "console", "sounds": True}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["skin"] == {"key": "console", "options": {"desk": "bricks"}, "sounds": True}
    assert user_client.patch("/api/v1/auth/me", headers=CSRF, json={"skin": {}}).json()["skin"] == {}


@pytest.mark.parametrize(("skin", "code"), [
    ({"key": "nothing"}, "no_such_skin"),
    ({"key": "1984", "options": {"desk": "moon"}}, "bad_skin_choice"),
    ({"key": "1984", "sounds": "loud"}, "bad_skin_choice"),
])
def test_an_account_cannot_wear_what_is_not_installed(skin: dict, code: str, user_client: TestClient) -> None:
    answer = user_client.patch("/api/v1/auth/me", headers=CSRF, json={"skin": skin})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == code


# Bringing one in ------------------------------------------------------------------------------------------------


def test_a_look_and_a_theme_come_in_as_skins_of_the_first_layer(admin_client: TestClient) -> None:
    from app.services import themes

    nord = next(theme for theme in themes.THEMES.values() if theme["name"] == "Nord")
    look = {"nexdeck_look": 1, "theme": nord, "card_style": "outline", "radius": 8, "gap": 10, "font": "geist", "accent": ""}
    first = admin_client.post("/api/v1/skins/import", headers=CSRF, json={"text": json.dumps(look)})
    assert first.status_code == 201, first.text
    assert first.json()["key"] == "nord"
    tokens = json.loads(admin_client.get("/api/v1/skins/nord/file").text)["tokens"]
    assert tokens["card_style"] == "outline" and tokens["radius"] == 8 and tokens["dark"]["bg"] == nord["dark"]["bg"].lower()
    second = admin_client.post("/api/v1/skins/import", headers=CSRF, json={"text": json.dumps({"nexdeck_theme": 1, **nord})})
    assert second.json()["key"] == "nord-2", "a second one with the same name gets a free key"


def test_a_look_that_is_1984_is_not_imported_twice(admin_client: TestClient) -> None:
    answer = admin_client.post("/api/v1/skins/import", headers=CSRF, json={"text": json.dumps({"nexdeck_look": 1, "card_style": "window"})})
    assert answer.json()["detail"]["code"] == "is_1984"


# Start and migration --------------------------------------------------------------------------------------------


def test_a_skin_compiled_by_an_older_engine_is_compiled_again_and_one_that_fails_is_switched_off(admin_client: TestClient) -> None:
    save_console(admin_client)
    broken = json.loads(CONSOLE)
    broken.update(key="old", css="[data-part=chip] { color: red !important }")
    with session_factory()() as db:
        db.query(Skin).update({Skin.engine: 0, Skin.compiled: {}})
        db.add(Skin(key="old", name="Old", text=json.dumps(broken), compiled={"css": "x"}, engine=0))
        db.commit()
        assert store.recompile_stale(db) == 2
        assert "--sk-sprite-coin" in store.compiled(db, "console")["css"]
        assert store.compiled(db, "old") is None


def test_migration_32_adds_the_table_and_a_column_an_older_version_can_insert_around(data_dir: Path) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE skins"))
        connection.execute(text("ALTER TABLE users DROP COLUMN skin"))
        connection.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO schema_version (version) VALUES (31)"))
    migrations.migrate()
    assert migrations.schema_version() == 32
    with engine.begin() as connection:
        assert {"key", "text", "compiled", "engine", "shop_ref"} <= {row[1] for row in connection.execute(text("PRAGMA table_info(skins)"))}
        # 1.0 writes accounts without the column it does not know: the database fills it in.
        skin = next(row for row in connection.execute(text("PRAGMA table_info(users)")) if row[1] == "skin")
        assert skin[3] == 1 and skin[4] == "'{}'"


def test_a_new_skin_starts_from_nothing_a_look_or_an_example_and_each_compiles(admin_client: TestClient, user_client: TestClient) -> None:
    starters = admin_client.get("/api/v1/skins/starters").json()["starters"]
    kinds = {starter["key"]: starter["kind"] for starter in starters}
    assert kinds["empty"] == "empty" and kinds["console"] == "example" and kinds["frost"] == "look"
    assert "1984" not in kinds, "1984 is nexdeck's own sheet, not data to start from"
    frost = json.loads(next(starter["text"] for starter in starters if starter["key"] == "frost"))
    assert frost["tokens"]["card_style"] == "outline" and len(frost["tokens"]["dark"]) == 15
    for starter in starters:
        assert admin_client.post("/api/v1/skins/check", headers=CSRF, json={"text": starter["text"]}).json()["ok"], starter["key"]
    assert user_client.get("/api/v1/skins/starters").status_code == 403


def test_the_workshop_makes_a_skin_worn_by_everybody_and_leaves_the_rest_of_the_look(admin_client: TestClient, user_client: TestClient) -> None:
    save_console(admin_client)
    assert admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "accent": "#123456", "skin": {"key": "1984", "options": {"desk": "weave"}}}).status_code == 200
    worn = admin_client.post("/api/v1/skins/console/wear", headers=CSRF, json={})
    assert worn.status_code == 200, worn.text
    assert worn.json()["skin"] == {"key": "console", "options": {"desk": "bricks"}}, "options left out take their defaults"
    assert worn.json()["card_style"] == "glass" and worn.json()["accent"] == "#123456"
    assert admin_client.post("/api/v1/skins/1984/wear", headers=CSRF, json={"options": {"desk": "grey"}}).json()["card_style"] == "window"
    assert admin_client.get("/api/v1/settings/appearance").json()["retro"]["desk"] == "grey"
    missing = admin_client.post("/api/v1/skins/nothing/wear", headers=CSRF, json={})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "no_such_skin"
    wrong = admin_client.post("/api/v1/skins/console/wear", headers=CSRF, json={"options": {"desk": "moon"}})
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "bad_skin_choice"
    assert user_client.post("/api/v1/skins/console/wear", headers=CSRF, json={}).status_code == 403


def test_the_default_skin_alone_is_changed_and_none_is_nexdeck_as_it_is(admin_client: TestClient, user_client: TestClient) -> None:
    save_console(admin_client)
    assert admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={**LOOK, "accent": "#123456", "skin": {"key": "1984"}}).status_code == 200
    made = admin_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": "console"})
    assert made.status_code == 200, made.text
    assert made.json()["skin"] == {"key": "console", "options": {"desk": "bricks"}} and made.json()["card_style"] == "glass" and made.json()["accent"] == "#123456"
    assert admin_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": "1984"}).json()["card_style"] == "window"
    none = admin_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": ""}).json()
    assert none["skin"] == {} and none["card_style"] == "glass", "none takes 1984's window away as well"
    missing = admin_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": "nothing"})
    assert missing.status_code == 400 and missing.json()["detail"]["code"] == "no_such_skin"
    assert user_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": ""}).status_code == 403


def test_an_account_may_wear_no_skin_whatever_the_installation_wears(user_client: TestClient, admin_client: TestClient) -> None:
    save_console(admin_client)
    assert admin_client.put("/api/v1/settings/appearance/skin", headers=CSRF, json={"key": "console"}).status_code == 200
    answer = user_client.patch("/api/v1/auth/me", headers=CSRF, json={"skin": {"plain": True, "key": "console", "sounds": True}})
    assert answer.status_code == 200 and answer.json()["skin"] == {"plain": True}
    assert user_client.get("/api/v1/auth/me").json()["skin"] == {"plain": True}
    assert user_client.patch("/api/v1/auth/me", headers=CSRF, json={"skin": {"plain": "yes"}}).json()["skin"] == {}, "only true is none"
