"""nexdeck's side of the shared sign-in module ``vendor/nexoidc``: the ``Store`` over its tables, the start-up
configuration, and the start-up check of the provider list.

The module (the blueprint "Anmeldung mit OIDC und authentik", the same in every nex app) runs the protocol, decides
who an identity is and keeps the provider list; it never sees a database. What is nexdeck's own lives here: accounts
and their names, the role of an account a provider creates, and the encryption of the client secrets.

A ``SqlStore`` works inside one SQLAlchemy session, one request. The module commits when an outcome is settled and
rolls back when it refuses after a write.

⚠️ The way back to 0.36. nexdeck kept its providers in a list before the module too, so there is no setting to
mirror; 0.36 reads the same rows. Its columns keep their names for one version (``models.OidcProvider``), every
write here keeps the secret in the form 0.36 reads as well, and every start runs ``sync_list``: whatever 0.36
changed or added in between is taken in (a provider 0.36 added keeps the callback it showed, a secret it changed
is taken over, an issuer it changed drops the links of the old one, because 0.36 kept them).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import SecretUnreadable, decrypt, decrypt_for, encrypt, encrypt_for
from ..db import db_session
from ..models import OidcLink, OidcProvider, Role, Setting, User, utcnow
from ..security import UNUSABLE_PASSWORD, has_usable_password
from ..vendor import nexoidc
from ..vendor.nexoidc import (
    AccountState,
    Invite,
    Link,
    Provider,
    ProviderValues,
    migrate,
    secret_context,
)
from ..vendor.nexoidc.protocol import same_issuer
from . import two_factor
from .public_url import public_url

logger = logging.getLogger("nexdeck.oidc")

APP_NAME = "nexdeck"
API_PREFIX = "/api/v1"
LOGIN_PAGE = "/login"
#: The profile page; "My account" in the blueprint.
ACCOUNT_PAGE = "/settings"
HOME = "/"
#: The callback nexdeck 0.36 and older sent to every provider. Their providers know it, so it stays valid for them.
OLD_CALLBACK = "/api/v1/auth/oidc/{slug}/callback"
#: What the list looked like the last time nexdeck wrote it: the issuer per entry (``sync_list``).
LIST_KEY = "oidc_list"
#: Longest account name (``schemas.UserCreate``).
NAME_MAX = 64
_NUMBERED = re.compile(r"^(.*?)(-\d+)$")
_NAME = re.compile(r"^[a-zA-Z0-9._-]+$")
#: An issuer of authentik, as the button of 0.36 set it up under the short name ``authentik``.
_AUTHENTIK_ISSUER = re.compile(r"/application/o/[-A-Za-z0-9_]+/?$")


def role_for_new_account(stored_role: str) -> str:
    """The role of an account a provider creates (blueprint 01: a member).

    ⚠️ 0.36 let the operator choose it per provider, administrator included: anybody with a login at that provider
    became an administrator here. New entries no longer offer the choice; an entry that had chosen "guest" keeps
    it, because a member may do more than a guest and nobody asked for that. Every other entry creates members.
    """
    return Role.guest.value if stored_role == Role.guest.value else Role.user.value


def _public_url() -> str:
    return public_url()


def _save_public_url(url: str) -> None:
    """The address the operator confirmed in the authentik card: the same setting the address page writes and
    ``public_url`` reads first, committed at once in a transaction of its own."""
    with db_session() as db:
        row = db.get(Setting, "general")
        value = dict(row.value or {}) if row is not None else {}
        value["public_url"] = url
        if row is None:
            db.add(Setting(key="general", value=value))
        else:
            row.value = value
        db.commit()


def _server_secret() -> str:
    return get_settings().resolved_secret_key()


def configure() -> None:
    """Tell the module who it runs in; once at start-up (and by the tests)."""
    nexoidc.configure(
        nexoidc.AppConfig(
            app_name=APP_NAME,
            server_secret=_server_secret,
            api_prefix=API_PREFIX,
            public_url=_public_url,
            save_public_url=_save_public_url,
            login_page=LOGIN_PAGE,
            account_page=ACCOUNT_PAGE,
            home=HOME,
        )
    )


def clean_name(raw: str) -> str:
    """An account name from what the provider suggests: nexdeck's characters, at most 64; a number at the end
    (``max-2``) survives the cut. Empty when nothing usable is left."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", raw.strip()).strip("-._")
    if len(cleaned) > NAME_MAX:
        numbered = _NUMBERED.match(cleaned)
        suffix = numbered.group(2) if numbered else ""
        stem = numbered.group(1) if numbered else cleaned
        cleaned = stem[: NAME_MAX - len(suffix)].rstrip("-._") + suffix
    return cleaned if _NAME.match(cleaned) else ""


def _secret_of(row: OidcProvider) -> str:
    try:
        return decrypt_for(row.client_secret_enc, secret_context(row.id))
    except SecretUnreadable:
        logger.error("The client secret of sign-in provider %s cannot be read; enter it again.", row.slug)
        return ""


def _seal(row: OidcProvider, secret: str) -> None:
    """The secret under the provider's own context, and in the form 0.36 reads (the way back)."""
    row.client_secret_enc = encrypt_for(secret, secret_context(row.id))
    row.legacy_secret = encrypt(secret) if secret else ""


def remember_list(db: Session) -> None:
    """Note the issuer of every entry as nexdeck wrote it; ``sync_list`` compares at the next start."""
    db.flush()
    issuers = {str(row.id): row.issuer for row in db.scalars(select(OidcProvider))}
    row = db.get(Setting, LIST_KEY)
    if row is None:
        db.add(Setting(key=LIST_KEY, value={"issuers": issuers}))
    elif (row.value or {}).get("issuers") != issuers:
        row.value = {"issuers": issuers}


class SqlStore:
    """``nexoidc.Store`` over ``oidc_providers`` and ``oidc_links``, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db
        #: Set by the return route before ``accounts.sign_in``: the entry a new account would come through, and the
        #: display name the provider sends (the module hands ``create_account`` only the account name).
        self.creating_for: int | None = None
        self.display_name: str = ""

    # --- Providers -------------------------------------------------------------------------------------------------

    def _provider(self, row: OidcProvider | None) -> Provider | None:
        if row is None:
            return None
        return Provider(
            id=row.id,
            slug=row.slug,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=_secret_of(row),
            scopes=row.scopes,
            enabled=row.enabled,
            auto_create=row.auto_create,
            trusts_second_factor=row.trusts_second_factor,
            managed=row.managed,
            position=row.position,
            redirect_path=row.redirect_path,
            created_at=row.created_at,
            registered_redirect=row.registered_redirect or "",
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id))
        return [provider for provider in (self._provider(row) for row in rows) if provider is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self.db.get(OidcProvider, provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcProvider).where(OidcProvider.slug == slug)))

    @staticmethod
    def _apply(row: OidcProvider, values: ProviderValues) -> None:
        row.slug, row.label, row.issuer, row.client_id = values.slug, values.label, values.issuer, values.client_id
        row.scopes, row.enabled, row.auto_create = values.scopes, values.enabled, values.auto_create
        row.trusts_second_factor, row.managed, row.position = (
            values.trusts_second_factor,
            values.managed,
            values.position,
        )
        row.redirect_path = values.redirect_path
        if values.registered_redirect is not None:
            row.registered_redirect = values.registered_redirect

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcProvider(legacy_secret="", default_role=Role.user.value)
        self._apply(row, values)
        if values.registered_redirect is None:
            row.registered_redirect = ""
        self.db.add(row)
        self.db.flush()
        _seal(row, values.client_secret or "")
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self.db.get(OidcProvider, provider_id)
        assert row is not None
        self._apply(row, values)
        if values.client_secret is not None:
            _seal(row, values.client_secret)
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def delete_provider(self, provider_id: int) -> None:
        # Foreign keys are on (db.py), the links would go anyway; said here so nothing depends on a pragma.
        self.drop_links(provider_id)
        self.db.execute(delete(OidcProvider).where(OidcProvider.id == provider_id))

    # --- Links -----------------------------------------------------------------------------------------------------

    @staticmethod
    def _link(row: OidcLink) -> Link:
        return Link(row.provider_id, row.subject, row.account_id, row.issuer, row.email or None, row.created_at,
                    row.last_used_at)

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        row = self.db.scalar(select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject))
        return self._link(row) if row else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def links_of_account(self, account_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.account_id == account_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def add_link(self, link: Link) -> None:
        self.db.add(OidcLink(provider_id=link.provider_id, subject=link.subject, account_id=link.account_id,
                             issuer=link.issuer, email=(link.email or "")[:300], created_at=utcnow()))
        self.db.flush()

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        result = self.db.execute(
            delete(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.account_id == account_id)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def drop_links(self, provider_id: int) -> int:
        result = self.db.execute(delete(OidcLink).where(OidcLink.provider_id == provider_id))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        self.db.execute(
            update(OidcLink)
            .where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
            .values(last_used_at=utcnow(), email=(email or "")[:300])
        )

    # --- Accounts --------------------------------------------------------------------------------------------------

    def account_state(self, account_id: int) -> AccountState | None:
        row = self.db.get(User, account_id)
        if row is None:
            return None
        return AccountState(row.id, row.username, row.disabled, has_usable_password(row.password_hash),
                            two_factor.enabled(row))

    def clean_name(self, raw: str) -> str:
        return clean_name(raw)

    def name_taken(self, name: str) -> bool:
        return self.db.scalar(select(User.id).where(func.lower(User.username) == name.lower())) is not None

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        """A new account without a password. The provider's address stays at the link only: an address here is
        where a password reset goes, and it is unique; the account sets its own."""
        stored = ""
        if self.creating_for is not None:
            entry = self.db.get(OidcProvider, self.creating_for)
            stored = entry.default_role if entry is not None else ""
        row = User(username=name, display_name=(self.display_name or name)[:120], password_hash=UNUSABLE_PASSWORD,
                   role=role_for_new_account(stored))
        self.db.add(row)
        self.db.flush()
        return row.id

    # --- Invitations: nexdeck has none ------------------------------------------------------------------------------

    def find_invite(self, key: str) -> Invite | None:
        return None

    def consume_invite(self, invite: Invite) -> bool:
        return False

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        return None

    # --- Transaction -----------------------------------------------------------------------------------------------

    def commit(self) -> None:
        remember_list(self.db)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


def _remembered(db: Session) -> dict[int, str] | None:
    row = db.get(Setting, LIST_KEY)
    if row is None:
        return None
    issuers = (row.value or {}).get("issuers") or {}
    return {int(key): str(value) for key, value in issuers.items() if str(key).isdigit()}


def sync_list(db: Session | None = None) -> dict[str, int]:
    """At every start, after the migrations: bring in what nexdeck 0.36 wrote since nexdeck wrote the list last.

    - An entry nexdeck has not seen (the first start after 0.36, or one 0.36 added after a way back) keeps the
      callback its provider knows (``OLD_CALLBACK``), goes to the end of the list, and counts as the authentik
      button's when it is the entry ``authentik`` 0.36's button made.
    - An issuer 0.36 changed drops every link of that entry: 0.36 kept them, and a subject is somebody only at the
      issuer that handed it out.
    - A short name 0.36 changed moves the old callback with it (0.36 showed that one).
    - A secret 0.36 entered is taken over; a link 0.36 made gets the issuer of its entry.

    Returns what it did, for the log and the tests."""
    if db is None:
        with db_session() as own:
            return sync_list(own)
    done = {"new": 0, "issuer_changed": 0, "links_dropped": 0, "renamed": 0, "secrets": 0, "links_filled": 0}
    remembered = _remembered(db)
    rows = list(db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id)))
    after = max((row.position for row in rows), default=-1) + 1
    for index, row in enumerate(rows):
        known = None if remembered is None else remembered.get(row.id)
        if known is None:
            done["new"] += 1
            if not row.redirect_path:
                row.redirect_path = migrate.old_callback(OLD_CALLBACK, row.slug)
            if not row.managed and row.slug == "authentik" and _AUTHENTIK_ISSUER.search(row.issuer or ""):
                row.managed = nexoidc.MANAGED_AUTHENTIK
            if remembered is None:
                row.position = index
            else:
                row.position, after = after, after + 1
            if row.created_at is None:
                row.created_at = utcnow()
        else:
            if not same_issuer(known, row.issuer or ""):
                dropped = int(db.execute(delete(OidcLink).where(OidcLink.provider_id == row.id)).rowcount or 0)  # type: ignore[attr-defined]
                done["issuer_changed"] += 1
                done["links_dropped"] += dropped
                logger.warning("OIDC issuer of provider %s changed in an older nexdeck, %d links dropped",
                               row.slug, dropped)
            old = migrate.old_callback(OLD_CALLBACK, row.slug)
            if row.redirect_path.startswith("/api/v1/auth/oidc/") and row.redirect_path != old:
                row.redirect_path = old
                done["renamed"] += 1
                logger.warning("Sign-in provider %s was renamed in an older nexdeck; its callback is now %s",
                               row.slug, old)
        try:
            legacy = decrypt(row.legacy_secret or "")
        except SecretUnreadable:
            legacy = None
        if legacy is not None:
            try:
                current: str | None = decrypt_for(row.client_secret_enc or "", secret_context(row.id))
            except SecretUnreadable:
                current = None
            if current != legacy:
                row.client_secret_enc = encrypt_for(legacy, secret_context(row.id))
                done["secrets"] += 1
        filled = db.execute(
            update(OidcLink).where(OidcLink.provider_id == row.id, OidcLink.issuer == "").values(issuer=row.issuer)
        )
        done["links_filled"] += int(filled.rowcount or 0)  # type: ignore[attr-defined]
    remember_list(db)
    db.commit()
    if any(done.values()):
        logger.info("Sign-in providers checked at start: %s", ", ".join(f"{k}={v}" for k, v in done.items() if v))
    return done


def account_links(db: Session) -> dict[int, list[dict[str, Any]]]:
    """Per account: the providers it is linked to, for the account list of the operator."""
    labels = {row.id: (row.slug, row.label) for row in db.scalars(select(OidcProvider))}
    found: dict[int, list[dict[str, Any]]] = {}
    for link in db.scalars(select(OidcLink).order_by(OidcLink.id)):
        slug, label = labels.get(link.provider_id, ("", ""))
        found.setdefault(link.account_id, []).append({"provider_id": link.provider_id, "slug": slug, "label": label})
    return found
