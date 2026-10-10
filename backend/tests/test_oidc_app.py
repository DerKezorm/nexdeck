"""nexdeck's own side of the shared sign-in module: what the contract tests in ``tests/nexoidc`` cannot see.

The way back to 0.36 (its columns kept, every start taking in what 0.36 wrote), the password switch, the second
factor duty after a provider, the proxy scheme, the brake, the role of a new account, the secret under its own
context, the address question of the settings route, the account list, and the two contract cases nexdeck can only
reach with ``auto_create`` because it has no invitations.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from .conftest import ADMIN, CSRF, create_user, login, setup_admin

sys.path.insert(0, str(Path(__file__).resolve().parent / "nexoidc"))
import oidc_fakes as fakes  # noqa: E402

OLD = "/api/v1/auth/oidc/{slug}/callback"


@pytest.fixture
def net() -> Iterator[fakes.Network]:
    from app.vendor import nexoidc

    network = fakes.Network()
    nexoidc.use_transport(network.transport())
    yield network
    nexoidc.use_transport(None)


def _location(response: Any) -> str:
    assert response.status_code in (302, 303, 307), (response.status_code, response.text[:200])
    return response.headers["location"]


def _add(client: TestClient, fake: fakes.FakeProvider, slug: str, **form: Any) -> dict[str, Any]:
    body = {"label": form.pop("label", slug), "slug": slug, "issuer": fake.issuer, "client_id": fake.client_id,
            "client_secret": fake.client_secret, **form}
    answer = client.post("/api/v1/oidc/admin/providers", json=body, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _round_trip(client: TestClient, fake: fakes.FakeProvider, slug: str) -> Any:
    target = _location(client.get(f"/api/v1/oidc/{slug}/start", follow_redirects=False))
    back = urlsplit(fakes.query_of(target)["redirect_uri"]).path
    return client.get(f"{back}?{urlencode(fake.authorize(target))}", follow_redirects=False)


def _browser() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def _db() -> Any:
    from app.db import session_factory

    return session_factory()()


# --- The way back to 0.36 ---------------------------------------------------------------------------------------


def _as_036(statement: str, **values: Any) -> None:
    """Write the way nexdeck 0.36 writes: plain SQL over the columns it knows, nothing else."""
    from app.db import get_engine

    with get_engine().begin() as connection:
        connection.execute(text(statement), values)


def test_a_database_made_by_this_version_still_takes_rows_as_036_writes_them(client: TestClient) -> None:
    """Every new column has a default the database knows, so 0.36 inserts on a database this version created."""
    from app.crypto import encrypt
    from app.security import hash_password

    _as_036("INSERT INTO users (username, display_name, password_hash, role, locale, theme, disabled, created_at,"
            " password_changed_ms, totp_secret, totp_confirmed, totp_last_step, seen_version, avatar, email,"
            " language_pair) VALUES ('old', 'old', :h, 'user', 'en', 'dark', 0, CURRENT_TIMESTAMP, 0, '', 0, 0, '',"
            " '', '', 'en,de')", h=hash_password("a-long-password"))
    _as_036("INSERT INTO sessions (user_id, created_at, last_seen_at, user_agent, revoked, kind, address)"
            " SELECT id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '', 0, 'password', '' FROM users WHERE username='old'")
    _as_036("INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes, enabled,"
            " auto_create, default_role, trusts_second_factor) VALUES ('old', 'Old', 'https://old.example.com', 'c',"
            " :s, 'openid profile email', 1, 0, 'user', 0)", s=encrypt("old-secret"))
    _as_036("INSERT INTO oidc_links (provider_id, user_id, subject, email) SELECT p.id, u.id, 'subject-1', ''"
            " FROM oidc_providers p, users u WHERE p.slug='old' AND u.username='old'")
    with _db() as db:
        row = db.execute(text("SELECT managed, position, redirect_path, registered_redirect, client_secret_enc"
                              " FROM oidc_providers WHERE slug='old'")).one()
        link = db.execute(text("SELECT issuer FROM oidc_links WHERE subject='subject-1'")).one()
    assert tuple(row) == ("", 0, "", "", "") and tuple(link) == ("",)


def test_the_first_start_keeps_the_old_callback_the_authentik_entry_and_the_secret(client: TestClient) -> None:
    from app.crypto import decrypt_for, encrypt
    from app.models import OidcLink, OidcProvider, Setting
    from app.services import oidc_store

    _as_036("DELETE FROM settings WHERE key = 'oidc_list'")
    _as_036("INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes, enabled,"
            " auto_create, default_role, trusts_second_factor) VALUES ('authentik', 'authentik',"
            " 'https://auth.example.com/application/o/nexdeck/', 'c', :s, 'openid', 1, 0, 'user', 0)",
            s=encrypt("kept-secret"))
    _as_036("INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes, enabled,"
            " auto_create, default_role, trusts_second_factor) VALUES ('keycloak', 'Keycloak',"
            " 'https://kc.example.com/realms/home', 'c', '', 'openid', 1, 0, 'user', 1)")
    setup_admin(client)
    _as_036("INSERT INTO oidc_links (provider_id, user_id, subject, email) SELECT p.id, 1, 's-1', ''"
            " FROM oidc_providers p WHERE p.slug='authentik'")
    done = oidc_store.sync_list()
    assert done["new"] == 2 and done["links_filled"] == 1
    with _db() as db:
        rows = {row.slug: row for row in db.scalars(select(OidcProvider))}
        assert rows["authentik"].redirect_path == "/api/v1/auth/oidc/authentik/callback"
        assert rows["keycloak"].redirect_path == "/api/v1/auth/oidc/keycloak/callback"
        assert rows["authentik"].managed == "authentik" and rows["keycloak"].managed == ""
        assert [rows["authentik"].position, rows["keycloak"].position] == [0, 1]
        # The issuer as 0.36 wrote it, slash and all; the module compares with same_issuer.
        assert rows["authentik"].issuer == "https://auth.example.com/application/o/nexdeck/"
        assert decrypt_for(rows["authentik"].client_secret_enc, f"oidc-provider:{rows['authentik'].id}") == "kept-secret"
        assert db.scalar(select(OidcLink.issuer)) == "https://auth.example.com/application/o/nexdeck/"
        assert db.get(Setting, "oidc_list") is not None
    # A second start does nothing more.
    assert not any(oidc_store.sync_list().values())


def test_what_036_changes_comes_in_at_the_next_start(client: TestClient, net: fakes.Network) -> None:
    from app.crypto import decrypt_for, encrypt
    from app.models import OidcLink, OidcProvider
    from app.services import oidc_store

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso")
    create_user(client, "alex")
    with _db() as db:
        db.add(OidcLink(provider_id=entry["id"], account_id=2, subject="alex-1", issuer=sso.issuer, email=""))
        db.commit()
    # 0.36 at work: another issuer (its PATCH kept the links), another secret, a new provider, a renamed one.
    _as_036("UPDATE oidc_providers SET issuer_url = 'https://other.example.com', client_secret = :s WHERE id = :i",
            s=encrypt("new-secret"), i=entry["id"])
    _as_036("INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes, enabled,"
            " auto_create, default_role, trusts_second_factor) VALUES ('later', 'Later', 'https://l.example.com',"
            " 'c', '', 'openid', 1, 0, 'user', 0)")
    done = oidc_store.sync_list()
    assert done["issuer_changed"] == 1 and done["links_dropped"] == 1 and done["new"] == 1 and done["secrets"] >= 1
    with _db() as db:
        row = db.get(OidcProvider, entry["id"])
        assert decrypt_for(row.client_secret_enc, f"oidc-provider:{row.id}") == "new-secret"
        later = db.scalar(select(OidcProvider).where(OidcProvider.slug == "later"))
        assert later.redirect_path == "/api/v1/auth/oidc/later/callback" and later.position > row.position
        assert db.scalar(select(OidcLink.id)) is None
    # A short name 0.36 changed moves the old callback with it; one of this version keeps its standard callback.
    _as_036("UPDATE oidc_providers SET slug = 'later2' WHERE slug = 'later'")
    assert oidc_store.sync_list()["renamed"] == 1
    with _db() as db:
        assert db.scalar(select(OidcProvider.redirect_path).where(OidcProvider.slug == "later2")) == OLD.format(slug="later2")
        assert db.get(OidcProvider, entry["id"]).redirect_path == ""


def test_every_write_keeps_the_secret_as_036_reads_it(client: TestClient, net: fakes.Network) -> None:
    from app.crypto import decrypt
    from app.models import OidcProvider

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso")
    with _db() as db:
        assert decrypt(db.get(OidcProvider, entry["id"]).legacy_secret) == sso.client_secret
    form = {"label": "sso", "issuer": sso.issuer, "client_id": sso.client_id, "client_secret": "another"}
    assert client.put(f"/api/v1/oidc/admin/providers/{entry['id']}", json=form, headers=CSRF).status_code == 200
    with _db() as db:
        assert decrypt(db.get(OidcProvider, entry["id"]).legacy_secret) == "another"


def test_a_secret_opens_under_its_own_provider_only(data_dir: Path) -> None:
    from app.crypto import SecretUnreadable, decrypt_for, encrypt_for

    sealed = encrypt_for("s3cret", "oidc-provider:1")
    assert decrypt_for(sealed, "oidc-provider:1") == "s3cret"
    with pytest.raises(SecretUnreadable):
        decrypt_for(sealed, "oidc-provider:2")


def test_a_backup_is_written_before_the_providers_change_shape(data_dir: Path) -> None:
    from app import migrations
    from app.db import get_engine
    from app.services import backup

    migrations.migrate()
    with get_engine().begin() as connection:
        connection.execute(text("INSERT INTO oidc_providers (slug, label, issuer_url, client_id, client_secret, scopes,"
                                " enabled, auto_create, default_role, trusts_second_factor) VALUES ('a', 'A',"
                                " 'https://a.example.com', 'c', '', 'openid', 1, 0, 'user', 0)"))
        connection.execute(text("DELETE FROM schema_version WHERE version >= 19"))
    before = len(backup.listing())
    migrations.migrate()
    assert len(backup.listing()) == before + 1
    assert any("before-sign-in-providers" in entry.name for entry in backup.listing())
    # Once through, no backup at the next start.
    migrations.migrate()
    assert len(backup.listing()) == before + 1


# --- Password sign-in --------------------------------------------------------------------------------------------


def test_the_password_switch_needs_an_active_provider_and_spares_administrators(
    client: TestClient, net: fakes.Network
) -> None:
    setup_admin(client)
    create_user(client, "member")
    refused = client.patch("/api/v1/settings", json={"password_login": False}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "no_active_provider"
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso")
    assert client.patch("/api/v1/settings", json={"password_login": False}, headers=CSRF).status_code == 200
    assert client.get("/api/v1/setup/status").json()["password_login"] is False
    member = _browser()
    answer = member.post("/api/v1/auth/login", json={"username": "member", "password": "another-long-password"})
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "bad_credentials"
    admin = _browser()
    assert admin.post("/api/v1/auth/login", json=ADMIN).status_code == 200
    # With no active provider left the switch has no effect: nobody is locked out by switching the last one off.
    form = {"label": "sso", "issuer": sso.issuer, "client_id": sso.client_id, "enabled": False}
    assert client.put(f"/api/v1/oidc/admin/providers/{entry['id']}", json=form, headers=CSRF).status_code == 200
    assert client.get("/api/v1/setup/status").json()["password_login"] is True
    assert member.post("/api/v1/auth/login", json={"username": "member", "password": "another-long-password"}).status_code == 200


# --- Second factor after a provider ------------------------------------------------------------------------------


def test_a_provider_that_checks_the_factor_spares_the_duty_in_that_session_only(
    client: TestClient, net: fakes.Network
) -> None:
    from app.db import session_factory
    from app.models import OidcLink, User

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso")
    create_user(client, "alex")
    with session_factory()() as db:
        alex = db.scalar(select(User).where(User.username == "alex"))
        db.add(OidcLink(provider_id=entry["id"], account_id=alex.id, subject="person-1", issuer=sso.issuer, email=""))
        db.commit()
    assert client.patch("/api/v1/settings", json={"require_two_factor": True}, headers=CSRF).status_code == 200
    via_provider = _browser()
    assert _location(_round_trip(via_provider, sso, "sso")) == "/"
    me = via_provider.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["keys_need_second_factor"] is True
    assert via_provider.get("/api/v1/boards").status_code == 200
    # The same account with its password is held at the door, and so are its API tokens.
    by_password = _browser()
    login(by_password, "alex", "another-long-password")
    held = by_password.get("/api/v1/boards")
    assert held.status_code == 403 and held.json()["detail"]["code"] == "two_factor_setup_required"
    token = via_provider.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF)
    assert token.status_code in (200, 201), token.text
    key = token.json()["token"]
    with _browser() as script:
        refused = script.get("/api/v1/boards", headers={"Authorization": f"Bearer {key}"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "two_factor_setup_required"
    # Not trusted with the factor: a password account is held after the provider too. (The administrator is held as
    # well now, so the switch is set in the database.)
    from app.models import OidcProvider

    with _db() as db:
        db.get(OidcProvider, entry["id"]).trusts_second_factor = False
        db.commit()
    untrusted = _browser()
    assert _location(_round_trip(untrusted, sso, "sso")) == "/"
    assert untrusted.get("/api/v1/boards").status_code == 403


def test_an_account_without_a_password_is_not_held_for_a_factor(client: TestClient, net: fakes.Network) -> None:
    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "sso", auto_create=True, trusts_second_factor=False)
    assert client.patch("/api/v1/settings", json={"require_two_factor": True}, headers=CSRF).status_code == 200
    browser = _browser()
    assert _location(_round_trip(browser, sso, "sso")) == "/"
    assert browser.get("/api/v1/boards").status_code == 200
    assert browser.get("/api/v1/auth/me").json()["keys_need_second_factor"] is False


# --- New accounts, and what the contract reaches through invitations ----------------------------------------------


@pytest.mark.parametrize(("stored", "made"), [("user", "user"), ("guest", "guest"), ("admin", "user")])
def test_a_new_account_is_a_member_and_a_guest_entry_stays_guest(
    client: TestClient, net: fakes.Network, stored: str, made: str
) -> None:
    from app.models import OidcProvider, User

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso", auto_create=True)
    with _db() as db:
        db.get(OidcProvider, entry["id"]).default_role = stored
        db.commit()
    browser = _browser()
    assert _location(_round_trip(browser, sso, "sso")) == "/"
    with _db() as db:
        alex = db.scalar(select(User).where(User.username == "alex"))
        assert alex.role == made and alex.display_name == "Alex Example" and alex.email == ""


def test_the_last_link_of_an_account_without_a_password_stays(client: TestClient, net: fakes.Network) -> None:
    """Contract test 18 without the invitation: the account comes from ``auto_create``."""
    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "sso", auto_create=True)
    browser = _browser()
    assert _location(_round_trip(browser, sso, "sso")) == "/"
    refused = browser.delete("/api/v1/oidc/sso/link", headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_only_account"


def test_a_new_account_from_entra_is_named_after_the_part_before_the_at(client: TestClient, net: fakes.Network) -> None:
    """Contract test 12 without the invitation."""
    setup_admin(client)
    entra = net.add(fakes.FakeEntra())
    answer = client.post("/api/v1/oidc/admin/providers", headers=CSRF, json={
        "label": "Microsoft", "slug": "entra", "issuer": fakes.ENTRA + "/common/v2.0", "client_id": entra.client_id,
        "client_secret": entra.client_secret, "auto_create": True})
    assert answer.status_code == 201, answer.text
    browser = _browser()
    assert _location(_round_trip(browser, entra, "entra")) == "/"
    assert browser.get("/api/v1/auth/me").json()["username"] == "max"


# --- Routes, brake, proxy ------------------------------------------------------------------------------------------


def test_a_provider_called_authentik_is_not_hidden_by_the_routes_of_the_button(
    client: TestClient, net: fakes.Network
) -> None:
    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "authentik", auto_create=True)
    browser = _browser()
    assert _location(_round_trip(browser, sso, "authentik")) == "/"
    # The button's own routes still answer; with a hand entry holding the short name, its entry would be another.
    assert client.get("/api/v1/oidc/authentik/address").json()["callback_path"] == "/api/v1/oidc/authentik-2/callback"
    assert client.get("/api/v1/oidc/authentik/blueprint").status_code == 409
    old = browser.get(OLD.format(slug="authentik") + "?error=x", follow_redirects=False)
    assert _location(old).startswith("/login?error=")


def test_a_return_without_its_own_attempt_never_feeds_the_brake(client: TestClient, net: fakes.Network) -> None:
    from app.services import login_guard

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "sso")
    stranger = _browser()
    for query in ("error=access_denied", "code=x&state=y", "garbage"):
        for _ in range(login_guard.MAX_PER_ADDRESS):
            stranger.get(f"/api/v1/oidc/sso/callback?{query}", follow_redirects=False)
            stranger.get(f"/api/v1/oidc/nobody/callback?{query}", follow_redirects=False)
    sso.person = {"sub": "nobody-known"}
    refused = _round_trip(stranger, sso, "sso")
    assert _location(refused) == "/login?error=oidc_no_account"


@pytest.mark.parametrize(
    ("sent", "trusted", "peer", "secure"),
    [
        ("https", "", "203.0.113.9", True),
        ("HTTPS", "", "203.0.113.9", True),
        ("https, http", "", "203.0.113.9", False),
        ("http, https", "", "203.0.113.9", True),
        ("ftp", "", "203.0.113.9", False),
        ("https", "10.0.0.0/8", "10.1.2.3", True),
        ("https", "10.0.0.0/8", "203.0.113.9", False),
    ],
)
def test_the_scheme_comes_from_the_rightmost_forwarded_proto_of_a_trusted_sender(
    monkeypatch: pytest.MonkeyPatch, sent: str, trusted: str, peer: str, secure: bool
) -> None:
    from app.services.home_network import forwarded_proto_headers

    monkeypatch.setenv("NEXDECK_TRUSTED_PROXIES", trusted)
    headers = forwarded_proto_headers([(b"host", b"deck.example.com"), (b"x-forwarded-proto", sent.encode())], peer)
    proto = [value for key, value in headers if key == b"x-forwarded-proto"]
    assert (proto == [b"https"]) is secure
    assert (b"host", b"deck.example.com") in headers


def test_behind_a_tls_proxy_the_sign_in_sends_https_and_a_secure_cookie(client: TestClient, net: fakes.Network) -> None:
    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "sso")
    answer = _browser().get("/api/v1/oidc/sso/start", headers={"X-Forwarded-Proto": "http, HTTPS"})
    assert fakes.query_of(_location(answer))["redirect_uri"].startswith("https://testserver/")
    assert "secure" in answer.headers["set-cookie"].lower()
    # The session cookie follows the same scheme (``cookie_secure``), not the raw header.
    signed = _browser().post("/api/v1/auth/login", json=ADMIN, headers={"X-Forwarded-Proto": "http, HTTPS"})
    assert signed.status_code == 200 and "secure" in signed.headers["set-cookie"].lower()
    plain = _browser().post("/api/v1/auth/login", json=ADMIN, headers={"X-Forwarded-Proto": "https, http"})
    assert plain.status_code == 200 and "secure" not in plain.headers["set-cookie"].lower()


# --- Settings, account list ---------------------------------------------------------------------------------------


def test_the_settings_route_asks_before_the_address_changes_and_refuses_one_that_is_none(
    client: TestClient, net: fakes.Network
) -> None:
    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    _add(client, sso, "sso")
    bad = client.patch("/api/v1/settings", json={"public_url": "not an address"}, headers=CSRF)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "public_url_invalid"
    asked = client.patch("/api/v1/settings", json={"public_url": "https://deck.example.com"}, headers=CSRF)
    assert asked.status_code == 409 and asked.json()["detail"]["hand"] == 1
    assert client.get("/api/v1/about").json()["public_url"] == ""
    assert client.patch("/api/v1/settings", json={"public_url": "https://deck.example.com", "confirm_address": True},
                        headers=CSRF).status_code == 200
    # Clearing it asks as well.
    cleared = client.patch("/api/v1/settings", json={"public_url": ""}, headers=CSRF)
    assert cleared.status_code == 409 and cleared.json()["detail"]["code"] == "public_url_change"


def test_the_account_list_names_the_providers_and_the_administrator_unlinks_with_the_password(
    client: TestClient, net: fakes.Network
) -> None:
    from app.models import OidcLink

    setup_admin(client)
    sso = net.add(fakes.FakeProvider())
    entry = _add(client, sso, "sso", label="Single sign-on")
    alex = create_user(client, "alex")
    with _db() as db:
        db.add(OidcLink(provider_id=entry["id"], account_id=alex["id"], subject="person-1", issuer=sso.issuer, email=""))
        db.commit()
    listed = {row["username"]: row for row in client.get("/api/v1/users").json()}
    assert listed["alex"]["providers"] == [{"provider_id": entry["id"], "slug": "sso", "label": "Single sign-on"}]
    path = f"/api/v1/oidc/admin/accounts/{alex['id']}/links/{entry['id']}"
    assert client.request("DELETE", path, json={"password": "wrong"}, headers=CSRF).status_code == 403
    assert client.request("DELETE", path, json={"password": ADMIN["password"]}, headers=CSRF).status_code == 204
    assert client.get("/api/v1/users").json()[1]["providers"] == []
