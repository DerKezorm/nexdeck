"""The authentik button against a fake authentik API v3, and the blueprint download.

The fake answers the calls in the order the service makes them and records
every request, so the tests can check that the token travels only in the
Authorization header, that the steps stop at the first failure and that an
existing provider is updated instead of duplicated. No network anywhere.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.adapters.base import outbound_client
from app.crypto import decrypt
from app.db import db_session
from app.models import OidcLink, OidcProvider, User
from app.services import authentik_setup, oidc

from .conftest import CSRF, create_user, login, setup_admin

URL = "https://auth.example.com"
TOKEN = "one-time-token-that-must-stay-out-of-everything"
ISSUER = f"{URL}/application/o/nexdeck/"
PUBLIC = "https://deck.example.com"
REDIRECT = f"{PUBLIC}/api/v1/auth/oidc/authentik/callback"


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    auth: str
    body: dict | None


@dataclass
class FakeAuthentik:
    """authentik as a MockTransport handler. ``existing`` says which objects are already there."""

    existing: set[str] = field(default_factory=set)
    fail: tuple[str, str, int] | None = None
    discovery_ok: bool = True
    provider_redirect: str = ""
    calls: list[Recorded] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "auth.example.com":
            raise httpx.ConnectError("no such host")
        method, path = request.method, request.url.path
        query = dict(request.url.params.items())
        body = json.loads(request.content) if request.content else None
        self.calls.append(Recorded(method, path, query, request.headers.get("authorization", ""), body))
        if self.fail and (method, path) == self.fail[:2]:
            return httpx.Response(self.fail[2], text="<html>authentik error page with secrets of its own</html>")
        if path.endswith("/.well-known/openid-configuration"):
            if not self.discovery_ok:
                return httpx.Response(404, text="not found")
            issuer = path.removesuffix(".well-known/openid-configuration")
            return httpx.Response(200, json={
                "issuer": f"{URL}{issuer}",
                "authorization_endpoint": f"{URL}{issuer}authorize/",
                "token_endpoint": f"{URL}/application/o/token/",
                "jwks_uri": f"{URL}{issuer}jwks/",
            })
        if not path.startswith("/api/v3/"):
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(403, json={"detail": "Authentication credentials were not provided."})
        return self._api(method, path[len("/api/v3"):], query, body)

    def _api(self, method: str, path: str, query: dict[str, str], body: dict | None) -> httpx.Response:
        if (method, path) == ("GET", "/admin/version/"):
            return httpx.Response(200, json={"version_current": "2026.8.1"})
        if (method, path) == ("GET", "/crypto/certificatekeypairs/"):
            rows = [{"pk": "cert-uuid", "name": "nexdeck"}] if "cert" in self.existing else []
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("POST", "/crypto/certificatekeypairs/generate/"):
            return httpx.Response(200, json={"pk": "cert-uuid", "name": body["common_name"]})
        if (method, path) == ("GET", "/propertymappings/provider/scope/"):
            rows = [
                {"pk": "map-openid", "managed": "goauthentik.io/providers/oauth2/scope-openid", "name": "default openid"},
                {"pk": "map-profile", "managed": "goauthentik.io/providers/oauth2/scope-profile", "name": "default profile"},
                {"pk": "map-email", "managed": "goauthentik.io/providers/oauth2/scope-email", "name": "default email"},
            ]
            if "mapping" in self.existing:
                rows.append({"pk": "map-own", "managed": None, "name": "nexdeck email_verified"})
            if "name" in query:
                rows = [row for row in rows if row["name"] == query["name"]]
            if "managed" in query:
                rows = [row for row in rows if row["managed"] == query["managed"]]
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("POST", "/propertymappings/provider/scope/"):
            return httpx.Response(201, json={"pk": "map-own", "name": body["name"]})
        if (method, path) == ("GET", "/flows/instances/"):
            if query.get("designation") == "authorization":
                rows = [
                    {"pk": "flow-explicit", "slug": "default-provider-authorization-explicit-consent"},
                    {"pk": "flow-implicit", "slug": "default-provider-authorization-implicit-consent"},
                ]
            else:
                rows = [{"pk": "flow-invalidation", "slug": "default-provider-invalidation-flow"}]
            return httpx.Response(200, json={"results": rows})
        if (method, path) == ("GET", "/providers/oauth2/"):
            rows = [{"pk": 7, "name": "nexdeck"}] if "provider" in self.existing else []
            if rows and self.provider_redirect:
                rows[0]["redirect_uris"] = [{"matching_mode": "strict", "url": self.provider_redirect}]
            if "name" in query:
                rows = [row for row in rows if row["name"] == query["name"]]
            return httpx.Response(200, json={"results": rows})
        if (method, path) in (("POST", "/providers/oauth2/"), ("PATCH", "/providers/oauth2/7/")):
            return httpx.Response(201 if method == "POST" else 200, json={**body, "pk": 7, "client_id": "generated-client-id", "client_secret": "generated-secret"})
        if (method, path) == ("GET", "/core/applications/"):
            rows = [{"pk": "app-uuid", "slug": "nexdeck"}] if "application" in self.existing else []
            if "slug" in query:
                rows = [row for row in rows if row["slug"] == query["slug"]]
            return httpx.Response(200, json={"results": rows})
        if method in ("POST", "PATCH") and path.startswith("/core/applications/"):
            return httpx.Response(201 if method == "POST" else 200, json={**body, "pk": "app-uuid"})
        return httpx.Response(404, json={"detail": f"no fake answer for {method} {path}"})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAuthentik]:
    server = FakeAuthentik()
    transport = httpx.MockTransport(server)
    monkeypatch.setattr(authentik_setup, "transport_for_tests", transport)
    # Discovery goes through the shared OIDC client; it gets the fake as well.
    monkeypatch.setattr(oidc, "_client", outbound_client(transport=transport))
    monkeypatch.setattr(oidc, "_discovery", {})
    yield server


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXDECK_PUBLIC_URL", PUBLIC)
    from app import config

    config.reset_settings_cache()
    setup_admin(client)
    return client


def run_setup(client: TestClient, url: str = URL, token: str = TOKEN) -> dict:
    response = client.post("/api/v1/oidc/authentik/setup", json={"url": url, "token": token}, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


def steps(result: dict) -> list[tuple[str, bool]]:
    return [(step["key"], step["ok"]) for step in result["steps"]]


def stored() -> OidcProvider | None:
    with db_session() as db:
        row = db.query(OidcProvider).filter(OidcProvider.slug == "authentik").one_or_none()
        if row is not None:
            db.expunge(row)
        return row


def test_setup_creates_everything_and_adds_the_sign_in_provider(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin)
    assert result["ok"] is True
    assert steps(result) == [(key, True) for key in authentik_setup.STEP_KEYS]
    assert result["client_id"] == "generated-client-id" and result["issuer"] == ISSUER
    assert "2026.8.1" in result["steps"][0]["detail"]

    row = stored()
    assert row is not None
    assert row.issuer_url == ISSUER.rstrip("/") and row.client_id == "generated-client-id" and row.enabled
    assert row.client_secret != "generated-secret" and decrypt(row.client_secret) == "generated-secret"
    # ⚠️ A provider the button made does not hand out accounts.
    assert row.auto_create is False and row.default_role == "user" and row.trusts_second_factor is False
    # The sign-in page offers it.
    assert any(p["slug"] == "authentik" for p in admin.get("/api/v1/auth/providers").json())

    created = [call for call in fake.calls if (call.method, call.path) == ("POST", "/api/v3/providers/oauth2/")]
    assert len(created) == 1
    body = created[0].body
    assert body["name"] == "nexdeck" and body["client_type"] == "confidential"
    # authentik 2026.8 refuses every authorize request whose grant is not listed on the provider.
    assert body["grant_types"] == ["authorization_code"]
    assert body["redirect_uris"] == [{"matching_mode": "strict", "url": REDIRECT}]
    assert body["signing_key"] == "cert-uuid" and body["sub_mode"] == "user_uuid"
    assert body["authorization_flow"] == "flow-implicit" and body["invalidation_flow"] == "flow-invalidation"
    assert sorted(body["property_mappings"]) == ["map-openid", "map-own", "map-profile"]


def test_the_token_goes_only_into_the_authorization_header(admin: TestClient, fake: FakeAuthentik, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    result = run_setup(admin)
    for call in fake.calls:
        if call.path.startswith("/api/v3/"):
            assert call.auth == f"Bearer {TOKEN}"
        assert TOKEN not in json.dumps(call.body or {}) and TOKEN not in json.dumps(call.query)
    assert TOKEN not in json.dumps(result)
    assert TOKEN not in caplog.text
    with db_session() as db:
        for row in db.query(OidcProvider).all():
            assert TOKEN not in (row.client_secret + row.client_id + row.issuer_url)


def test_pressing_it_again_updates_instead_of_duplicating(admin: TestClient, fake: FakeAuthentik) -> None:
    run_setup(admin)
    fake.existing |= {"cert", "mapping", "provider", "application"}
    fake.calls.clear()
    result = run_setup(admin)
    assert result["ok"] is True
    methods = {(call.method, call.path) for call in fake.calls}
    assert ("PATCH", "/api/v3/providers/oauth2/7/") in methods
    assert ("PATCH", "/api/v3/core/applications/nexdeck/") in methods
    assert not any(method == "POST" for method, _ in methods), methods
    with db_session() as db:
        assert db.query(OidcProvider).count() == 1


def test_the_first_failure_stops_the_run_and_names_the_status_not_the_answer(admin: TestClient, fake: FakeAuthentik) -> None:
    fake.fail = ("POST", "/api/v3/providers/oauth2/", 403)
    result = run_setup(admin)
    assert result["ok"] is False
    assert steps(result) == [("reached", True), ("signingKey", True), ("mapping", True), ("provider", False)]
    detail = result["steps"][-1]["detail"]
    assert "403" in detail and "may not" in detail
    assert "secrets of its own" not in detail, "the body of a foreign answer must not go back to the browser"
    assert stored() is None


def test_a_wrong_token_stops_at_the_first_step(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin, token="not-the-token")
    assert steps(result) == [("reached", False)]
    assert stored() is None


def test_an_unreachable_authentik_is_named(admin: TestClient, fake: FakeAuthentik) -> None:
    result = run_setup(admin, url="https://nowhere.example.com")
    assert steps(result) == [("reached", False)]
    assert "not reachable" in result["steps"][0]["detail"]


def test_a_second_nexdeck_does_not_take_over_the_first_ones_provider(admin: TestClient, fake: FakeAuthentik) -> None:
    fake.existing |= {"provider"}
    fake.provider_redirect = "https://deck.other.example.com/api/v1/auth/oidc/authentik/callback"
    result = run_setup(admin)
    assert result["ok"] is True
    assert result["issuer"] == f"{URL}/application/o/nexdeck-deck-example-com/"
    created = [call for call in fake.calls if (call.method, call.path) == ("POST", "/api/v3/providers/oauth2/")]
    assert created and created[0].body["name"] == "nexdeck (deck.example.com)"


def test_a_failed_discovery_keeps_what_authentik_handed_out(admin: TestClient, fake: FakeAuthentik) -> None:
    fake.discovery_ok = False
    result = run_setup(admin)
    assert steps(result)[-1] == ("filled", False)
    assert "discovery" in result["steps"][-1]["detail"]
    row = stored()
    assert row is not None and row.client_id == "generated-client-id"


def test_a_new_issuer_drops_the_links_of_the_old_one(admin: TestClient, fake: FakeAuthentik, caplog: pytest.LogCaptureFixture) -> None:
    """⚠️ A subject means something only at the issuer that handed it out."""
    caplog.set_level(logging.INFO)
    made = admin.post("/api/v1/oidc/providers", headers=CSRF, json={
        "slug": "authentik", "label": "authentik", "issuer_url": "https://old.example.com/application/o/deck/",
        "client_id": "old", "client_secret": "old-secret",
    })
    assert made.status_code == 201, made.text
    with db_session() as db:
        user = db.query(User).first()
        db.add(OidcLink(provider_id=made.json()["id"], user_id=user.id, subject="from-the-old-issuer", email=""))
    assert run_setup(admin)["ok"] is True
    with db_session() as db:
        assert db.query(OidcLink).count() == 0
        assert db.query(OidcProvider).count() == 1
    # The same line as a change by hand: one wording for one event.
    assert "OIDC issuer of provider authentik changed, 1 links dropped" in caplog.text


def test_a_new_issuer_is_logged_even_with_nothing_to_drop(admin: TestClient, fake: FakeAuthentik, caplog: pytest.LogCaptureFixture) -> None:
    made = admin.post("/api/v1/oidc/providers", headers=CSRF, json={
        "slug": "authentik", "label": "authentik", "issuer_url": "https://old.example.com/application/o/deck/",
        "client_id": "old", "client_secret": "old-secret",
    })
    assert made.status_code == 201, made.text
    caplog.set_level(logging.INFO)
    assert run_setup(admin)["ok"] is True
    assert "OIDC issuer of provider authentik changed, 0 links dropped" in caplog.text


def test_the_button_after_a_hand_entry_of_the_same_issuer_drops_nothing(admin: TestClient, fake: FakeAuthentik, caplog: pytest.LogCaptureFixture) -> None:
    """The operator typed authentik's issuer by hand, with a space and the slash at the end, then pressed the button."""
    made = admin.post("/api/v1/oidc/providers", headers=CSRF, json={
        "slug": "authentik", "label": "authentik", "issuer_url": f" {ISSUER} ", "client_id": "old", "client_secret": "old-secret",
    })
    caplog.set_level(logging.INFO)
    assert made.status_code == 201, made.text
    assert made.json()["issuer_url"] == ISSUER.rstrip("/"), "stored without spaces and without the slash at the end"
    with db_session() as db:
        user = db.query(User).first()
        db.add(OidcLink(provider_id=made.json()["id"], user_id=user.id, subject="from-the-same-issuer", email=""))
    assert run_setup(admin)["ok"] is True
    with db_session() as db:
        assert db.query(OidcLink).count() == 1
    assert "issuer of provider" not in caplog.text, "the same issuer is no change"


def test_the_button_compares_a_stored_issuer_as_the_same_issuer(admin: TestClient, fake: FakeAuthentik) -> None:
    """A row stored before the form cleaned the issuer up still counts as the same one."""
    made = admin.post("/api/v1/oidc/providers", headers=CSRF, json={
        "slug": "authentik", "label": "authentik", "issuer_url": ISSUER, "client_id": "old", "client_secret": "old-secret",
    })
    assert made.status_code == 201, made.text
    with db_session() as db:
        row = db.get(OidcProvider, made.json()["id"])
        row.issuer_url = f"{ISSUER} "
        user = db.query(User).first()
        db.add(OidcLink(provider_id=row.id, user_id=user.id, subject="from-the-same-issuer", email=""))
    assert run_setup(admin)["ok"] is True
    with db_session() as db:
        assert db.query(OidcLink).count() == 1


def test_only_an_administrator_may_press_it(admin: TestClient, fake: FakeAuthentik) -> None:
    create_user(admin, "kim")
    browser = TestClient(admin.app)
    login(browser, "kim", "another-long-password")
    refused = browser.post("/api/v1/oidc/authentik/setup", json={"url": URL, "token": TOKEN}, headers=CSRF)
    assert refused.status_code == 403
    assert browser.get("/api/v1/oidc/authentik/blueprint").status_code == 403
    assert fake.calls == []


def test_without_a_public_address_nothing_is_sent(client: TestClient, fake: FakeAuthentik, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXDECK_PUBLIC_URL", raising=False)
    from app import config

    config.reset_settings_cache()
    setup_admin(client)
    refused = client.post("/api/v1/oidc/authentik/setup", json={"url": URL, "token": TOKEN}, headers=CSRF)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "no_public_url"
    assert fake.calls == []


def test_the_blueprint_describes_the_same_objects(admin: TestClient) -> None:
    answer = admin.get("/api/v1/oidc/authentik/blueprint")
    assert answer.status_code == 200
    assert "nexdeck-authentik.yaml" in answer.headers["content-disposition"]

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: f"!{suffix}")
    document = yaml.load(answer.text, Loader=Loader)  # noqa: S506
    models = [entry["model"] for entry in document["entries"]]
    assert models == ["authentik_providers_oauth2.scopemapping", "authentik_providers_oauth2.oauth2provider", "authentik_core.application"]
    provider = document["entries"][1]["attrs"]
    assert provider["grant_types"] == ["authorization_code"]
    assert provider["redirect_uris"] == [{"matching_mode": "strict", "url": REDIRECT}]
