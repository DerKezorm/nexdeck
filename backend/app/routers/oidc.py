"""OIDC sign-in and provider management."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..deps import AdminUser, DbSession, error
from ..models import OidcLink, OidcProvider, Role, User
from ..schemas import OidcProviderBody
from ..security import UNUSABLE_PASSWORD
from ..services import login_guard, oidc
from .auth import cookie_secure, open_session
from .system import get_setting

router = APIRouter(prefix="/api/v1", tags=["oidc"])
logger = logging.getLogger("nexdeck.oidc")


def _provider(db: DbSession, slug: str) -> OidcProvider:
    provider = db.scalar(select(OidcProvider).where(OidcProvider.slug == slug, OidcProvider.enabled.is_(True)))
    if provider is None:
        raise error("not_found", "There is no such sign-in provider.", status.HTTP_404_NOT_FOUND)
    return provider


def _to_app(path: str, **params: str) -> RedirectResponse:
    base = get_settings().url_base
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"{base}{path}{'?' + query if query else ''}", status_code=status.HTTP_303_SEE_OTHER)


def _public_url(db: DbSession) -> str:
    return str(get_setting(db, "general").get("public_url") or get_settings().public_url)


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
    response.set_cookie(oidc.COOKIE_NAME, oidc.pack_state(slug, attempt), max_age=oidc.ATTEMPT_MINUTES * 60, path=f"{get_settings().url_base}/api/v1/auth/oidc",
                        httponly=True, samesite="lax", secure=cookie_secure(request))
    return response


@router.get("/auth/oidc/{slug}/callback", summary="Return from the identity provider")
async def oidc_callback(slug: str, request: Request, db: DbSession, code: str | None = None, state: str | None = None, error_: str | None = None) -> RedirectResponse:
    """Every outcome is a redirect to the app with a code in the address; never JSON."""
    provider = _provider(db, slug)
    attempt = oidc.unpack_state(request.cookies.get(oidc.COOKIE_NAME))
    address = request.client.host if request.client else "?"

    def refuse(code_: str, reason: str) -> RedirectResponse:
        logger.warning("OIDC callback refused for %r: %s", slug, reason)
        response = _to_app("/login", oidc_error=code_)
        response.delete_cookie(oidc.COOKIE_NAME, path=f"{get_settings().url_base}/api/v1/auth/oidc")
        return response

    if request.query_params.get("error"):
        return refuse("oidc_denied", f"provider returned {request.query_params.get('error')!r}")
    if attempt is None or attempt.get("slug") != slug or not code or not state or attempt.get("state") != state:
        return refuse("oidc_state_mismatch", "state or cookie does not match the running attempt")
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
    email = str(payload.get("email") or info.get("email") or "")
    preferred = str(payload.get("preferred_username") or info.get("preferred_username") or email.split("@")[0] or f"user-{subject[:8]}")
    display = str(payload.get("name") or info.get("name") or preferred)
    link = db.scalar(select(OidcLink).where(OidcLink.provider_id == provider.id, OidcLink.subject == subject))
    if link is not None:
        user = db.get(User, link.user_id)
    else:
        if not provider.auto_create:
            return refuse("oidc_no_account", "no linked account and auto-create is off")
        username = re.sub(r"[^a-zA-Z0-9._-]", "-", preferred)[:64] or f"user-{subject[:8]}"
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            username = f"{username}-{subject[:6]}"
        user = User(username=username, display_name=display[:120], password_hash=UNUSABLE_PASSWORD, role=provider.default_role)
        db.add(user)
        db.flush()
        db.add(OidcLink(provider_id=provider.id, user_id=user.id, subject=subject, email=email[:300]))
        db.commit()
        logger.info("OIDC created account %r via %r.", user.username, slug)
    if user is None or user.disabled:
        return refuse("oidc_disabled", "the linked account is disabled or gone")
    login_guard.succeeded(address)
    response = _to_app("/")
    response.delete_cookie(oidc.COOKIE_NAME, path=f"{get_settings().url_base}/api/v1/auth/oidc")
    open_session(db, user, request, response)
    return response


# -- administration ----------------------------------------------------------


def _provider_public(provider: OidcProvider) -> dict:
    return {"id": provider.id, "slug": provider.slug, "label": provider.label, "issuer_url": provider.issuer_url, "client_id": provider.client_id,
            "has_secret": bool(provider.client_secret), "scopes": provider.scopes, "enabled": provider.enabled, "auto_create": provider.auto_create, "default_role": provider.default_role}


@router.get("/oidc/providers", summary="List identity providers")
def list_providers(admin: AdminUser, db: DbSession) -> list[dict]:
    return [_provider_public(p) for p in db.scalars(select(OidcProvider).order_by(OidcProvider.id))]


@router.post("/oidc/providers", status_code=status.HTTP_201_CREATED, summary="Add an identity provider")
def create_provider(body: OidcProviderBody, admin: AdminUser, db: DbSession) -> dict:
    if db.scalar(select(OidcProvider).where(OidcProvider.slug == body.slug)):
        raise error("taken", "That slug is taken.", status.HTTP_409_CONFLICT)
    provider = OidcProvider(slug=body.slug, label=body.label, issuer_url=body.issuer_url.rstrip("/"), client_id=body.client_id,
                            client_secret=encrypt(body.client_secret) if body.client_secret else "", scopes=body.scopes, enabled=body.enabled,
                            auto_create=body.auto_create, default_role=body.default_role)
    db.add(provider)
    db.commit()
    return _provider_public(provider)


@router.patch("/oidc/providers/{provider_id}", summary="Change an identity provider")
def patch_provider(provider_id: int, body: OidcProviderBody, admin: AdminUser, db: DbSession) -> dict:
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise error("not_found", "There is no such provider.", status.HTTP_404_NOT_FOUND)
    provider.slug = body.slug
    provider.label = body.label
    provider.issuer_url = body.issuer_url.rstrip("/")
    provider.client_id = body.client_id
    if body.client_secret:
        provider.client_secret = encrypt(body.client_secret)
    provider.scopes = body.scopes
    provider.enabled = body.enabled
    provider.auto_create = body.auto_create
    provider.default_role = body.default_role
    db.commit()
    return _provider_public(provider)


@router.delete("/oidc/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an identity provider")
def delete_provider(provider_id: int, admin: AdminUser, db: DbSession) -> None:
    provider = db.get(OidcProvider, provider_id)
    if provider is None:
        raise error("not_found", "There is no such provider.", status.HTTP_404_NOT_FOUND)
    db.delete(provider)
    db.commit()


def _role_check(role: str) -> str:
    return role if role in {r.value for r in Role} else Role.user.value
