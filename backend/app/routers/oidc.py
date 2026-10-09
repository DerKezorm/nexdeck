"""OIDC sign-in and provider management."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select

from ..crypto import decrypt, encrypt
from ..deps import AdminUser, DbSession, PasswordUser, error, refuse_at_home
from ..models import OidcLink, OidcProvider, Role, User
from ..schemas import AuthentikSetupBody, OidcProviderBody
from ..security import UNUSABLE_PASSWORD, create_step_token, has_usable_password
from ..services import authentik_setup, login_guard, oidc, two_factor
from ..services.public_url import public_url
from .auth import STEP_COOKIE, STEP_MINUTES, cookie_secure, open_session

router = APIRouter(prefix="/api/v1", tags=["oidc"])
logger = logging.getLogger("nexdeck.oidc")

#: Where a linking attempt ends, with ``oidc_linked`` or ``oidc_error`` in the address.
PROFILE_PAGE = "/settings"


def _provider(db: DbSession, slug: str) -> OidcProvider:
    provider = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug, OidcProvider.enabled.is_(True)))
    if provider is None:
        raise error("not_found", "There is no such sign-in provider.", status.HTTP_404_NOT_FOUND)
    return provider


def _to_app(path: str, **params: str) -> RedirectResponse:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"{path}{'?' + query if query else ''}", status_code=status.HTTP_303_SEE_OTHER)


def _public_url(db: DbSession) -> str:
    return public_url(db)


@router.get("/auth/oidc/{slug}/login", summary="Start a sign-in at an identity provider")
async def oidc_login(slug: str, request: Request, db: DbSession) -> RedirectResponse:
    provider = _provider(db, slug)
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = oidc.redirect_uri(_public_url(db), slug)
    except oidc.OidcError as failure:
        logger.warning("OIDC sign-in via %r could not start: %s", slug, failure.message)
        return _to_app("/login", oidc_error=failure.code)
    attempt = oidc.new_attempt()
    response = RedirectResponse(oidc.authorization_url(document, provider.client_id, redirect, provider.scopes, attempt), status_code=status.HTTP_302_FOUND)
    response.set_cookie(oidc.COOKIE_NAME, oidc.pack_state(slug, attempt), max_age=oidc.ATTEMPT_MINUTES * 60, path="/api/v1/auth/oidc",
                        httponly=True, samesite="lax", secure=cookie_secure(request))
    return response


@router.get("/auth/oidc/{slug}/callback", summary="Return from the identity provider")
async def oidc_callback(slug: str, request: Request, db: DbSession, code: str | None = None, state: str | None = None, error_: str | None = None) -> RedirectResponse:
    """Every outcome is a redirect to the app with a code in the address; never JSON."""
    provider = _provider(db, slug)
    attempt = oidc.unpack_state(request.cookies.get(oidc.COOKIE_NAME))
    address = request.client.host if request.client else "?"
    linking = attempt is not None and attempt.get("purpose") == "link"

    def refuse(code_: str, reason: str) -> RedirectResponse:
        logger.warning("OIDC callback refused for %r: %s", slug, reason)
        # A linking attempt started on the profile page and goes back there; a
        # sign-in has no page to go back to but the sign-in page.
        response = _to_app(PROFILE_PAGE if linking else "/login", oidc_error=code_)
        response.delete_cookie(oidc.COOKIE_NAME, path="/api/v1/auth/oidc")
        return response

    if request.query_params.get("error"):
        return refuse("oidc_denied", f"provider returned {request.query_params.get('error')!r}")
    if attempt is None or attempt.get("slug") != slug or not code or not state or attempt.get("state") != state:
        return refuse("oidc_state_mismatch", "state or cookie does not match the running attempt")
    if not oidc.consume_state(state):
        # The same cookie and state a second time: a copy of the callback, played back.
        return refuse("oidc_state_mismatch", "this state was used already")
    try:
        # No account name here yet; the address bucket is all there is.
        login_guard.check(address)
    except login_guard.TooManyAttempts:
        return refuse("oidc_too_many", "too many failed attempts from this address")
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = oidc.redirect_uri(_public_url(db), slug)
        tokens = await oidc.exchange(document, provider.client_id, decrypt(provider.client_secret) if provider.client_secret else "", redirect, code, attempt["verifier"])
        id_token = tokens.get("id_token")
        if not id_token:
            raise oidc.OidcError("oidc_bad_token", "The provider sent no ID token.")
        payload = await oidc.claims(document, provider.client_id, id_token, attempt["nonce"], provider.issuer_url)
        info = await oidc.userinfo(document, tokens.get("access_token", ""))
    except oidc.OidcError as failure:
        login_guard.failed(address)
        return refuse(failure.code, failure.message)
    subject = str(payload.get("sub") or "")
    if not subject:
        # ⚠️ Without this, the empty string became the key of the identity, and
        # the second person whose provider omits ``sub`` would have been let
        # into the account of the first. jwt.decode does not require the claim.
        login_guard.failed(address)
        return refuse("oidc_bad_token", "the ID token has no subject")
    email = str(payload.get("email") or info.get("email") or "")
    if linking:
        login_guard.succeeded(address)
        return _finish_link(db, provider, attempt, subject, email, refuse)
    preferred = str(payload.get("preferred_username") or info.get("preferred_username") or email.split("@")[0] or f"user-{subject[:8]}")
    display = str(payload.get("name") or info.get("name") or preferred)
    link = db.scalar(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.subject == subject))
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        if not provider.auto_create:
            return refuse("oidc_no_account", "no linked account and auto-create is off")
        username = re.sub(r"[^a-zA-Z0-9._-]", "-", preferred)[:64] or f"user-{subject[:8]}"
        # ⚠️ Two goes are not enough. Adding the subject once was the whole
        # collision handling, so a second person with the same preferred name
        # and a subject starting with the same six characters walked into a
        # unique constraint, and the callback answered 500 with a stack trace.
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            username = f"{username}-{subject[:6]}"
        attempt_number = 2
        while db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            username = f"{username[:58]}-{attempt_number}"
            attempt_number += 1
            if attempt_number > 50:
                return refuse("oidc_name_taken", "no free user name could be made from the provider's claims")
        user = User(username=username, display_name=display[:120], password_hash=UNUSABLE_PASSWORD, role=provider.default_role)
        db.add(user)
        db.flush()
        db.add(OidcLink(provider_id=provider.id, user_id=user.id, subject=subject, email=email[:300]))
        db.commit()
        logger.info("OIDC created account %r via %r.", user.username, slug)
    if user is None or user.disabled:
        return refuse("oidc_disabled", "the linked account is disabled or gone")
    login_guard.succeeded(address)
    if two_factor.enabled(user) and not provider.trusts_second_factor:
        # ⚠️ The provider proved who this is; it did not prove the second
        # factor. Until 07.09.2026 this path opened a session outright, so an
        # account with a confirmed authenticator app was let in without a code
        # as long as it came through OIDC. The ticket travels in a short-lived
        # cookie rather than in the address: this is a redirect, and anything
        # in the address stands in the proxy log.
        logger.info("%s came in through %r and now needs a code.", user.username, slug)
        response = _to_app("/login", second_step="1")
        response.delete_cookie(oidc.COOKIE_NAME, path="/api/v1/auth/oidc")
        response.set_cookie(
            STEP_COOKIE, create_step_token(user.id), max_age=STEP_MINUTES * 60, httponly=True,
            samesite="lax", secure=cookie_secure(request), path="/api/v1/auth",
        )
        return response
    response = _to_app("/")
    response.delete_cookie(oidc.COOKIE_NAME, path="/api/v1/auth/oidc")
    open_session(db, user, request, response)
    return response


def _finish_link(db: DbSession, provider: OidcProvider, attempt: dict, subject: str, email: str, refuse) -> RedirectResponse:  # noqa: ANN001
    """Store the identity on the account that asked, instead of signing anybody in.

    ⚠️ Only this way, never through the address. authentik lets a user change
    their own address by default, so linking an account whose address matches
    would let anybody with an authentik login into the account of whoever's
    address they typed, the administrator's included.
    """
    user = db.get(User, int(attempt.get("user_id") or 0))
    if user is None or user.disabled:
        return refuse("oidc_disabled", "the account that asked to link is disabled or gone")
    taken = db.scalar(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.subject == subject))
    if taken is not None and taken.user_id != user.id:
        return refuse("oidc_taken", f"that identity is linked to another account already (user id {taken.user_id})")
    if taken is None:
        # One identity per provider and account: linking again replaces the old one.
        for old in db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.user_id == user.id)):
            db.delete(old)
        db.add(OidcLink(provider_id=provider.id, user_id=user.id, subject=subject, email=email[:300]))
        db.commit()
    logger.info("%s linked their account to %r.", user.username, provider.slug)
    response = _to_app(PROFILE_PAGE, oidc_linked=provider.slug)
    response.delete_cookie(oidc.COOKIE_NAME, path="/api/v1/auth/oidc")
    return response


# -- one's own links ---------------------------------------------------------


@router.get("/auth/oidc/links", summary="The sign-in providers and whether this account is linked to each")
def my_links(user: PasswordUser, db: DbSession) -> list[dict]:
    linked = {link.provider_id for link in db.scalars(select(OidcLink).where(OidcLink.user_id == user.id))}
    return [
        {"slug": p.slug, "label": p.label, "linked": p.id in linked}
        for p in db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.id))
    ]


@router.post("/auth/oidc/{slug}/link", summary="Start linking this account to an identity provider")
async def link_start(slug: str, request: Request, user: PasswordUser, db: DbSession) -> JSONResponse:
    """Answers with the address to go to, and sets the attempt cookie on the way.

    A POST, not a link to follow: it carries the CSRF header like every other
    change, so no other page can start a linking attempt in somebody's browser.
    """
    provider = _provider(db, slug)
    try:
        document = await oidc.discovery(provider.issuer_url)
        redirect = oidc.redirect_uri(_public_url(db), slug)
    except oidc.OidcError as failure:
        raise error(failure.code, failure.message, status.HTTP_502_BAD_GATEWAY) from None
    attempt = oidc.new_attempt()
    response = JSONResponse({"url": oidc.authorization_url(document, provider.client_id, redirect, provider.scopes, attempt)})
    response.set_cookie(oidc.COOKIE_NAME, oidc.pack_state(slug, attempt, purpose="link", user_id=user.id), max_age=oidc.ATTEMPT_MINUTES * 60,
                        path="/api/v1/auth/oidc", httponly=True, samesite="lax", secure=cookie_secure(request))
    return response


@router.delete("/auth/oidc/{slug}/link", status_code=status.HTTP_204_NO_CONTENT, summary="Undo the link to an identity provider")
def link_remove(slug: str, user: PasswordUser, db: DbSession) -> None:
    provider = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug))
    if provider is None:
        raise error("not_found", "There is no such sign-in provider.", status.HTTP_404_NOT_FOUND)
    links = list(db.scalars(select(OidcLink).where(OidcLink.user_id == user.id)))
    mine = [link for link in links if link.provider_id == provider.id]
    if mine and not has_usable_password(user.password_hash) and len(links) == len(mine):
        # ⚠️ The last way into an account without a password.
        raise error("would_lock_out", "This is the only way into this account. Set a password first.", status.HTTP_409_CONFLICT)
    for link in mine:
        db.delete(link)
    db.commit()


# -- administration ----------------------------------------------------------


def _authentik_redirect(db: DbSession) -> str:
    try:
        return oidc.redirect_uri(_public_url(db), authentik_setup.PROVIDER_SLUG)
    except oidc.OidcError as failure:
        raise error("no_public_url", failure.message, status.HTTP_422_UNPROCESSABLE_ENTITY) from None


@router.post("/oidc/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup_run(body: AuthentikSetupBody, request: Request, admin: AdminUser, db: DbSession) -> dict:
    """⚠️ The token is used for this run only: not stored, not logged, not echoed."""
    refuse_at_home(request)
    url = body.url.strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise error("bad_url", "The authentik address must start with http:// or https://.", status.HTTP_422_UNPROCESSABLE_ENTITY)
    redirect = _authentik_redirect(db)
    logger.info("authentik setup started for %s by %s.", url, admin.username)
    result = await authentik_setup.setup(db, url, body.token.strip(), redirect)
    return result.as_dict()


@router.get("/oidc/authentik/blueprint", summary="Download a blueprint that creates the same objects in authentik")
def authentik_blueprint(admin: AdminUser, db: DbSession) -> Response:
    return Response(
        content=authentik_setup.blueprint(_authentik_redirect(db)),
        media_type="application/yaml",
        headers={"Content-Disposition": 'attachment; filename="nexdeck-authentik.yaml"'},
    )


def _link_count(db: DbSession, provider_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(OidcLink).where(OidcLink.provider_id == provider_id)) or 0)


def _provider_public(db: DbSession, provider: OidcProvider) -> dict:
    """``links``: how many accounts are linked to it, for the question before its issuer changes."""
    return {"id": provider.id, "slug": provider.slug, "label": provider.label, "issuer_url": provider.issuer_url, "client_id": provider.client_id,
            "has_secret": bool(provider.client_secret), "scopes": provider.scopes, "enabled": provider.enabled, "auto_create": provider.auto_create, "default_role": provider.default_role,
            "trusts_second_factor": provider.trusts_second_factor, "links": _link_count(db, provider.id)}


@router.get("/oidc/providers", summary="List identity providers")
def list_providers(admin: AdminUser, db: DbSession) -> list[dict]:
    return [_provider_public(db, p) for p in db.scalars(select(OidcProvider).order_by(OidcProvider.id))]


@router.get("/oidc/providers/{provider_id}", summary="One identity provider, with the number of linked accounts")
def get_provider(provider_id: int, admin: AdminUser, db: DbSession) -> dict:
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise error("not_found", "There is no such provider.", status.HTTP_404_NOT_FOUND)
    return _provider_public(db, provider)


@router.post("/oidc/providers", status_code=status.HTTP_201_CREATED, summary="Add an identity provider")
def create_provider(body: OidcProviderBody, admin: AdminUser, db: DbSession) -> dict:
    if db.scalar(select(OidcProvider).where(OidcProvider.slug == body.slug)):
        raise error("taken", "That slug is taken.", status.HTTP_409_CONFLICT)
    provider = OidcProvider(slug=body.slug, label=body.label, issuer_url=oidc.normal_issuer(body.issuer_url), client_id=body.client_id,
                            client_secret=encrypt(body.client_secret) if body.client_secret else "", scopes=body.scopes, enabled=body.enabled,
                            auto_create=body.auto_create, default_role=body.default_role, trusts_second_factor=body.trusts_second_factor)
    db.add(provider)
    db.commit()
    return _provider_public(db, provider)


@router.patch("/oidc/providers/{provider_id}", summary="Change an identity provider")
def patch_provider(provider_id: int, body: OidcProviderBody, admin: AdminUser, db: DbSession) -> dict:
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise error("not_found", "There is no such provider.", status.HTTP_404_NOT_FOUND)
    # ⚠️ The same check POST has. Without it the unique constraint answered,
    # and a unique constraint answers with 500 and a stack trace.
    clash = db.scalar(select(OidcProvider).where(OidcProvider.slug == body.slug, OidcProvider.id != provider_id))
    if clash is not None:
        raise error("taken", "That slug is taken.", status.HTTP_409_CONFLICT)
    if not oidc.same_issuer(provider.issuer_url, body.issuer_url):
        # ⚠️ Another issuer is another provider. A subject means something only
        # at the issuer that handed it out; kept across the change, a subject at
        # the new one that happens to equal an old one would sign in as that
        # account. The form asks first, with the number.
        gone = list(db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id)))
        for link in gone:
            db.delete(link)
        oidc.forget_discovery(provider.issuer_url)
        logger.warning("OIDC issuer of provider %s changed, %d links dropped", body.slug, len(gone))
    provider.slug = body.slug
    provider.label = body.label
    provider.issuer_url = oidc.normal_issuer(body.issuer_url)
    provider.client_id = body.client_id
    if body.client_secret:
        provider.client_secret = encrypt(body.client_secret)
    provider.scopes = body.scopes
    provider.enabled = body.enabled
    provider.auto_create = body.auto_create
    provider.default_role = body.default_role
    provider.trusts_second_factor = body.trusts_second_factor
    db.commit()
    return _provider_public(db, provider)


@router.delete("/oidc/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an identity provider")
def delete_provider(provider_id: int, admin: AdminUser, db: DbSession, force: bool = False) -> None:
    """⚠️ Removing a provider takes its links with it (``ondelete="CASCADE"``).

    An account created through that provider has ``UNUSABLE_PASSWORD`` and no
    other way in, so deleting the provider locks it out for good, silently and
    with no undo. Counting them first and saying the number is the difference
    between a decision and an accident. ``force=true`` goes ahead anyway.
    """
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise error("not_found", "There is no such provider.", status.HTTP_404_NOT_FOUND)
    if not force:
        stranded = [
            user.username
            for link in db.scalars(select(OidcLink).where(OidcLink.provider_id == provider.id))
            if (user := db.get(User, link.user_id)) is not None
            and not has_usable_password(user.password_hash)
            and db.scalar(select(func.count()).select_from(OidcLink).where(OidcLink.user_id == link.user_id)) == 1
        ]
        if stranded:
            raise error(
                "would_lock_out",
                f"{len(stranded)} account(s) have no password and no other provider: {', '.join(sorted(stranded)[:5])}. "
                "Give them a password first, or repeat with force=true.",
                status.HTTP_409_CONFLICT,
            )
    db.delete(provider)
    db.commit()


def _role_check(role: str) -> str:
    return role if role in {r.value for r in Role} else Role.user.value
