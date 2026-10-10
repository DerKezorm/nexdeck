"""nexoidc contract tests: nexdeck's adapter (copied once from ``bauplaene/oidc/tests-fuer-apps/adapter_template.py``,
from then on nexdeck's own file).

The contract tests in ``tests/nexoidc/`` are the same in every nex app and never edited here. They reach nexdeck only
through this class: its real routes, a fresh database per test, its accounts and its second factor. Passwords and
keys are made at run time; none is written into this file.

nexdeck has no invitations (#job-193: the invitation parts of the blueprint do not apply). The contract tests have
no switch for that, so ``make_invite`` skips the test that asks for one, by name and with the reason; what those
tests check besides the invitation (the last link of an account without a password, the name of a new account
from Entra) is checked with ``auto_create`` in ``tests/test_oidc_app.py``.
"""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx
import pyotp
import pytest
from fastapi.testclient import TestClient
from oidc_contract import StandardAdapter
from sqlalchemy import func, select

#: The environment one test runs in; taken back afterwards.
ENVIRONMENT = ("NEXDECK_DATA_DIR", "NEXDECK_SECRET_KEY", "NEXDECK_DEMO", "NEXDECK_LOG_LEVEL", "NEXDECK_PUBLIC_URL",
               "NEXDECK_BCRYPT_ROUNDS", "NEXDECK_COOKIE_SECURE")
OPERATOR_NAME = "operator"


class Adapter(StandardAdapter):
    package = "app.vendor.nexoidc"
    api = "/api/v1"
    single_account = False
    only_authentik = False
    #: nexdeck is not part of the nexsuite Verbund (blueprint 06 names nexcanvas, nextasks, nexbrand, nexlore).
    supports_coupling = False
    has_second_factor = True
    legacy_model = "list"
    old_callback_paths: tuple[str, ...] = ("/api/v1/auth/oidc/{slug}/callback",)
    operator_name = OPERATOR_NAME
    origin = "http://testserver"
    anonymous_status: tuple[int, ...] = (401,)
    member_status: tuple[int, ...] = (403,)
    home = "/"
    login_page = "/login"
    account_page = "/settings"

    def start(self) -> None:
        from app import config, crypto, db
        from app.migrations import migrate
        from app.services import login_guard, oidc_store

        self._folder = tempfile.mkdtemp(prefix="nexdeck-oidc-")
        self._saved = {name: os.environ.get(name) for name in ENVIRONMENT}
        os.environ.update({
            "NEXDECK_DATA_DIR": self._folder,
            "NEXDECK_SECRET_KEY": secrets.token_urlsafe(32),
            "NEXDECK_DEMO": "0",
            "NEXDECK_LOG_LEVEL": "WARNING",
            "NEXDECK_BCRYPT_ROUNDS": "4",
        })
        os.environ.pop("NEXDECK_PUBLIC_URL", None)
        os.environ.pop("NEXDECK_COOKIE_SECURE", None)
        config.reset_settings_cache()
        db.reset_engine()
        crypto.forget_key()
        login_guard.reset()
        oidc_store.configure()
        migrate()
        oidc_store.sync_list()
        self._operator: TestClient | None = None
        self._seeds: dict[str, str] = {}
        self.make_account(OPERATOR_NAME, role="admin")

    def stop(self) -> None:
        from app import config, crypto, db
        from app.services import login_guard

        db.reset_engine()
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_settings_cache()
        crypto.forget_key()
        login_guard.reset()
        shutil.rmtree(self._folder, ignore_errors=True)

    def browser(self) -> TestClient:
        from app.main import app

        # As the interface does: every change carries the header a form on another site cannot add.
        return TestClient(app, base_url="http://testserver", follow_redirects=False,
                          headers={"X-Nexdeck-Request": "1"})

    def operator(self) -> TestClient:
        if self._operator is None:
            self._operator = self.browser()
            self.sign_in_with_password(self._operator, OPERATOR_NAME)
        return self._operator

    def make_account(self, name: str, *, password: bool = True, second_factor: bool = False, role: str = "user") -> int:
        from app.db import session_factory
        from app.models import User
        from app.security import UNUSABLE_PASSWORD, hash_password
        from app.services import two_factor

        with session_factory()() as db:
            row = User(username=name, display_name=name, role=role,
                       password_hash=hash_password(self.password_for(name)) if password else UNUSABLE_PASSWORD)
            if second_factor:
                seed = two_factor.new_secret()
                self._seeds[name] = seed
                two_factor.store_secret(row, seed)
                row.totp_confirmed = True
            db.add(row)
            db.commit()
            return row.id

    def _code(self, name: str) -> str:
        from app.db import session_factory
        from app.models import User
        from app.services.two_factor import STEP_SECONDS, TOLERANCE

        with session_factory()() as db:
            last = db.scalar(select(User.totp_last_step).where(User.username == name)) or 0
        now = int(time.time()) // STEP_SECONDS
        step = max(now - TOLERANCE, last + 1)
        assert step <= now + TOLERANCE, "no unused step left for a code"
        return pyotp.TOTP(self._seeds[name], interval=STEP_SECONDS).at(step * STEP_SECONDS)

    def sign_in_with_password(self, client: Any, name: str) -> None:
        answer = client.post("/api/v1/auth/login", json={"username": name, "password": self.password_for(name)})
        if answer.status_code == 401 and answer.json().get("detail", {}).get("code") == "second_step":
            ticket = answer.json()["detail"]["ticket"]
            answer = client.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "code": self._code(name)})
        assert answer.status_code == 200, answer.text

    def who(self, client: Any) -> str | None:
        answer = client.get("/api/v1/auth/me")
        return answer.json()["username"] if answer.status_code == 200 else None

    def second_factor_asked(self, client: Any, response: httpx.Response) -> bool:
        from app.routers.auth import STEP_COOKIE
        from app.security import read_step_token

        waiting = client.cookies.get(STEP_COOKIE)
        return (
            response.headers.get("location", "") == "/login?second_step=1"
            and waiting is not None
            and read_step_token(waiting) is not None
        )

    def make_invite(self, rights: str) -> str:
        pytest.skip("nexdeck has no invitations (#job-193); checked with auto_create in tests/test_oidc_app.py")

    def rights_of(self, name: str) -> str | None:
        from app.db import session_factory
        from app.models import User

        with session_factory()() as db:
            role = db.scalar(select(User.role).where(func.lower(User.username) == name.lower()))
        return None if role is None else "member"

    def account_names(self) -> list[str]:
        from app.db import session_factory
        from app.models import User

        with session_factory()() as db:
            return sorted(db.scalars(select(User.username)))

    def store(self) -> AbstractContextManager[Any]:
        from app.db import session_factory
        from app.services.oidc_store import SqlStore

        @contextmanager
        def opened() -> Iterator[SqlStore]:
            db = session_factory()()
            try:
                yield SqlStore(db)
            finally:
                db.close()

        return opened()

    def trip_throttle(self, client: Any) -> None:
        # As many failed attempts from this sender as the brake lets pass (every TestClient is "testclient").
        from app.services import login_guard

        for _ in range(login_guard.MAX_PER_ADDRESS):
            login_guard.failed("testclient")

    def set_public_url(self, url: str) -> None:
        from app.services.oidc_store import _save_public_url

        _save_public_url(url)

    def read_public_url(self) -> str:
        from app.db import session_factory
        from app.models import Setting

        with session_factory()() as db:
            row = db.get(Setting, "general")
            return str((row.value or {}).get("public_url") or "") if row is not None else ""

    def save_public_url_route(self, url: str, *, confirm: bool = False) -> httpx.Response:
        # Card 1 and the address page save the address in the settings route, which asks
        # ``authentik.public_url_guard`` first.
        body: dict[str, Any] = {"public_url": url}
        if confirm:
            body["confirm_address"] = True
        return self.operator().patch("/api/v1/settings", json=body)

    def delete_account(self, name: str) -> None:
        from app.db import session_factory
        from app.models import User

        with session_factory()() as db:
            account_id = db.scalar(select(User.id).where(User.username == name))
        answer = self.operator().delete(f"/api/v1/users/{account_id}")
        assert answer.status_code == 204, answer.text
