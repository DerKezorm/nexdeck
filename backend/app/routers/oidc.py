"""Sign-in through OpenID Connect providers, their list, linking, and the authentik button.

The protocol, who an identity is, the provider list and the button live in the shared module ``vendor/nexoidc``
(the blueprint "Anmeldung mit OIDC und authentik", the same in every nex app); this router puts nexdeck around it:
sessions, the sign-in brake, the password asked again before linking, the second factor, and the error answers.

The return leg is a browser redirect, not an API answer: every outcome of a callback ends in a redirect, to ``/``
with the session cookie, to the sign-in page with ``?error=<code>``, to ``/login?second_step=1`` when the code of
nexdeck's own second factor is still due, or to the profile page after linking.

Paths (all below ``/api/v1/oidc``):

| Method | Path | Who |
|---|---|---|
| GET | ``/providers`` | anybody: slug and label of the active entries (sign-in page) |
| GET, POST | ``/admin/providers`` | administrator: the list (never a secret), add one |
| PUT | ``/admin/providers/order`` | administrator: ``{"ids": [...]}`` |
| PUT, DELETE | ``/admin/providers/{id}`` | administrator: save (``dropped`` links), remove (``count``, ``only``) |
| GET | ``/admin/providers/{id}/impact?issuer=`` | administrator: the numbers for the two confirmations |
| GET | ``/{slug}/start`` | anybody: off to the provider |
| GET | ``/{slug}/callback`` | anybody: the return |
| GET | ``/me`` | signed in: every active entry with ``linked`` |
| POST, DELETE | ``/{slug}/link`` | signed in: link (``{"password"}`` → ``{"url"}``), unlink |
| DELETE | ``/admin/accounts/{account}/links/{provider}`` | administrator, with the own password |
| POST | ``/authentik/setup`` | administrator: ``{"url", "token", "confirm_issuer_change", "public_url"}`` → 200 |
| GET, POST | ``/authentik/address`` | administrator: the public address for the card; save it ("Use it only") |
| GET | ``/authentik/blueprint`` | administrator: ``nexdeck-authentik.yaml``; 409 without a public address |

The providers of nexdeck 0.36 and older know ``/api/v1/auth/oidc/<slug>/callback``; those entries carry it as their
``redirect_path`` and come back through the second route below. ``/api/v1/auth/oidc/<slug>/login`` stays a start, for
links somebody kept.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..db import session_factory
from ..deps import AdminUser, CurrentUser, PasswordUser, error, refuse_at_home
from ..models import User
from ..security import create_step_token, has_usable_password, verify_password
from ..services import login_guard
from ..services.oidc_store import SqlStore
from ..vendor.nexoidc import OidcError, ProviderInvalid, authentik, flow, providers
from ..vendor.nexoidc import accounts as oidc_accounts
from ..vendor.nexoidc import attempt as oidc_attempt
from ..vendor.nexoidc.config import current
from .auth import STEP_COOKIE, STEP_MINUTES, cookie_secure, open_session

router = APIRouter(prefix="/api/v1", tags=["oidc"])
logger = logging.getLogger("nexdeck.oidc")

#: The sign-in page, asking for the code of nexdeck's own second factor after a provider that is not trusted with it.
CODE_STEP = "/login?second_step=1"
#: Refusals that cost nothing to produce (a forged or replayed return, a braked sender, an unknown provider): they
#: never count against the sender. Nor does any return without a valid attempt cookie of this browser.
FREE_REFUSALS = ("oidc_state_mismatch", "too_many_attempts", "oidc_not_configured")
#: A session opened through a provider that checks the second factor itself: not held at the door to set one up.
SESSION_VIA_PROVIDER = "provider"


class ProviderIn(BaseModel):
    label: str = Field(max_length=200)
    slug: str = Field(default="", max_length=100)
    issuer: str = Field(max_length=600)
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = True
    auto_create: bool = False
    trusts_second_factor: bool = True


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=200)


class SetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)
    #: The answer to the button's question "another issuer, {count} accounts link again".
    confirm_issuer_change: bool = False
    #: The address the administrator confirmed in the card (the browser's own) while nexdeck has none.
    public_url: str = Field(default="", max_length=600)


class AddressIn(BaseModel):
    public_url: str = Field(max_length=600)
    confirm: bool = False


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


@contextmanager
def store() -> Iterator[SqlStore]:
    db = session_factory()()
    try:
        yield SqlStore(db)
    finally:
        db.close()


def _base(request: Request) -> str:
    return str(request.base_url)


def _sender(request: Request) -> str:
    return request.client.host if request.client else "?"


def _redirect(target: flow.Redirect, request: Request) -> RedirectResponse:
    # 303: the browser loads the target with GET whatever way it came.
    response = RedirectResponse(target.location, status_code=status.HTTP_303_SEE_OTHER)
    cookie = target.cookie
    secure = cookie.secure or cookie_secure(request)
    if cookie.max_age == 0:
        response.delete_cookie(cookie.name, path=cookie.path, secure=secure, httponly=True, samesite="lax")
    else:
        response.set_cookie(cookie.name, cookie.value, max_age=cookie.max_age, path=cookie.path,
                            httponly=cookie.http_only, samesite="lax", secure=secure)
    return response


def _form_error(exc: ProviderInvalid) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail={"code": exc.code, "message": exc.message, "field": exc.field})


def _braked(request: Request) -> bool:
    try:
        login_guard.check(_sender(request))
    except login_guard.TooManyAttempts:
        return True
    return False


# --- The provider list -------------------------------------------------------------------------------------------


@router.get("/oidc/providers", summary="The active sign-in providers: slug and label (no sign-in needed)")
def public_providers() -> list[dict[str, str]]:
    with store() as s:
        return providers.public_list(s)


@router.get("/oidc/admin/providers", summary="The provider list for the administrator (never a secret)")
def admin_providers(_admin: AdminUser, request: Request) -> list[dict[str, Any]]:
    with store() as s:
        coupled = providers.coupled(s)
        return [providers.admin_view(entry, _base(request), len(s.links_of_provider(entry.id)), coupled=coupled)
                for entry in s.list_providers()]


@router.post("/oidc/admin/providers", status_code=status.HTTP_201_CREATED,
             summary="Add a provider; the issuer is checked by discovery")
async def add_provider(payload: ProviderIn, admin: AdminUser, request: Request) -> dict[str, Any]:
    with store() as s:
        try:
            created = await providers.create(s, providers.Form(**payload.model_dump()))
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s added by=%s", created.slug, admin.username)
        return providers.admin_view(created, _base(request), 0)


@router.put("/oidc/admin/providers/order", summary="Put the providers in this order (the drag handle)")
def order_providers(payload: OrderIn, _admin: AdminUser) -> list[dict[str, str]]:
    with store() as s:
        try:
            providers.reorder(s, payload.ids)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        return providers.public_list(s)


@router.put("/oidc/admin/providers/{provider_id}", summary="Save a provider; another issuer drops its links")
async def save_provider(
    provider_id: Annotated[int, Path(ge=1)], payload: ProviderIn, admin: AdminUser, request: Request
) -> dict[str, Any]:
    with store() as s:
        try:
            saved, dropped = await providers.update(s, provider_id, providers.Form(**payload.model_dump()))
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s saved by=%s", saved.slug, admin.username)
        view = providers.admin_view(saved, _base(request), len(s.links_of_provider(saved.id)))
        return {**view, "dropped": dropped}


@router.get("/oidc/admin/providers/{provider_id}/impact", summary="Who loses a link when the issuer changes or it goes")
def provider_impact(
    provider_id: Annotated[int, Path(ge=1)],
    _admin: AdminUser,
    issuer: Annotated[str, Query(max_length=600)] = "",
) -> dict[str, Any]:
    with store() as s:
        if s.get_provider(provider_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail={"code": "provider_unknown", "message": "No such provider.", "field": "id"})
        removal = providers.removal_impact(s, provider_id)
        change = providers.issuer_change_impact(s, provider_id, issuer) if issuer else 0
        return {"issuer_change": change, **asdict(removal)}


@router.delete("/oidc/admin/providers/{provider_id}", summary="Remove a provider with its links")
def remove_provider(provider_id: Annotated[int, Path(ge=1)], admin: AdminUser) -> dict[str, Any]:
    with store() as s:
        try:
            impact = providers.remove(s, provider_id)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
    logger.info("OIDC provider %s removed by=%s", provider_id, admin.username)
    return asdict(impact)


# --- Start and return --------------------------------------------------------------------------------------------


@router.get("/oidc/{slug}/start", summary="Send the browser to the provider (no sign-in needed)")
async def start(
    slug: Annotated[str, Path(max_length=40)],
    request: Request,
    invite: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = None,
) -> RedirectResponse:
    # nexdeck has no invitations: an ``?invite=`` names none, so the module refuses it with ``invite_invalid``.
    with store() as s:
        try:
            if _braked(request):
                raise OidcError("too_many_attempts", "sender is braked")
            target = await flow.begin(s, slug, request_base=_base(request), invite=invite)
        except OidcError as exc:
            return _redirect(flow.refused(exc, None), request)
    return _redirect(target, request)


@router.get("/auth/oidc/{slug}/login", include_in_schema=False)
async def old_start(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    """The start as nexdeck 0.36 named it; a bookmark of it still works."""
    return await start(slug, request, None)


async def _returned(slug: str, request: Request) -> RedirectResponse:
    """The return from the provider. The order is the module's: the provider's own error, our cookie and state, the
    single use of the state, then the provider; nothing is written before all that passed."""
    cookie = request.cookies.get(current().cookie_name)
    sender = _sender(request)
    with store() as s:
        try:
            if _braked(request):
                raise OidcError("too_many_attempts", "sender is braked")
            arrival = await flow.finish(s, slug, cookie=cookie, params=dict(request.query_params))
            if arrival.started.purpose == oidc_attempt.LINK:
                account = _signed_in(request, s)
                oidc_accounts.link(s, arrival, account.id if account else None)
                return _redirect(flow.arrived(arrival, flow.linked_page(slug)), request)
            s.creating_for = arrival.provider.id
            s.display_name = arrival.identity.name or ""
            signed = oidc_accounts.sign_in(s, arrival)
        except OidcError as exc:
            # ⚠️ Only a return that carries this browser's own attempt counts against the sender. Anybody can send
            # ``?error=`` or rubbish to the callback; counted, that would lock a whole household out of signing in.
            if exc.code not in FREE_REFUSALS and oidc_attempt.read(cookie) is not None:
                login_guard.failed(sender)
            return _redirect(flow.refused(exc, cookie), request)
        user = s.db.get(User, signed.account_id)
        assert user is not None
        if signed.second_factor_due:
            # The provider is not trusted with the second factor and the account has one here: the same waiting
            # sign-in as after the password; the code step of the sign-in page finishes it.
            response = _redirect(flow.arrived(arrival, CODE_STEP), request)
            response.set_cookie(STEP_COOKIE, create_step_token(user.id), max_age=STEP_MINUTES * 60, httponly=True,
                                samesite="lax", secure=cookie_secure(request), path="/api/v1/auth")
            logger.info("Provider accepted, second factor waiting name=%s", user.username)
            return response
        response = _redirect(flow.arrived(arrival), request)
        # A provider the entry trusts with the second factor spares the duty to set one up in this session.
        kind = SESSION_VIA_PROVIDER if arrival.provider.trusts_second_factor else "password"
        open_session(s.db, user, request, response, kind=kind)
        return response


@router.get("/oidc/{slug}/callback", summary="The return from the provider (no sign-in needed)")
async def callback(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    return await _returned(slug, request)


@router.get("/auth/oidc/{slug}/callback", summary="The return, at the address providers of nexdeck 0.36 know")
async def old_callback(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    return await _returned(slug, request)


def _signed_in(request: Request, s: SqlStore) -> User | None:
    """The account of this browser's session, without the dependency (the return is a plain GET)."""
    from ..deps import _user_from_cookie

    return _user_from_cookie(request, s.db)


# --- My account --------------------------------------------------------------------------------------------------


@router.get("/oidc/me", summary="The active providers and whether the own account is linked to each")
def my_providers(user: CurrentUser) -> list[dict[str, Any]]:
    with store() as s:
        linked = {link.provider_id for link in s.links_of_account(user.id)}
        return [{"slug": entry.slug, "label": entry.label, "linked": entry.id in linked}
                for entry in s.list_providers() if entry.enabled]


@router.post("/oidc/{slug}/link", summary="Start linking the own account to a provider; needs the password")
async def link_start(
    slug: Annotated[str, Path(max_length=40)], payload: PasswordIn, request: Request, response: Response,
    user: PasswordUser,
) -> dict[str, str]:
    """Linking hands the account to whoever the browser is at the provider, so it asks for the password again."""
    sender = _sender(request)
    try:
        login_guard.check(sender, user.username)
    except login_guard.TooManyAttempts:
        raise error("too_many_attempts", "Too many attempts. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS) from None
    if not has_usable_password(user.password_hash):
        raise error("oidc_only_account", "This account has no password; it signs in through a provider.",
                    status.HTTP_409_CONFLICT)
    if not verify_password(payload.password, user.password_hash):
        login_guard.failed(sender, user.username)
        raise error("bad_credentials", "The password is wrong.", status.HTTP_403_FORBIDDEN)
    login_guard.succeeded(sender, user.username)
    with store() as s:
        try:
            target = await flow.begin(s, slug, request_base=_base(request), link_account_id=user.id)
        except OidcError as exc:
            raise error(exc.code, exc.message, status.HTTP_409_CONFLICT) from exc
    cookie = target.cookie
    response.set_cookie(cookie.name, cookie.value, max_age=cookie.max_age, path=cookie.path, httponly=True,
                        samesite="lax", secure=cookie.secure or cookie_secure(request))
    logger.info("OIDC linking to provider %s started name=%s", slug, user.username)
    return {"url": target.location}


@router.delete("/oidc/{slug}/link", status_code=status.HTTP_204_NO_CONTENT,
               summary="Unlink the own account from a provider")
def unlink(slug: Annotated[str, Path(max_length=40)], user: CurrentUser) -> None:
    with store() as s:
        entry = s.provider_by_slug(slug)
        if entry is None:
            raise error("oidc_not_configured", "This provider is not set up.", status.HTTP_404_NOT_FOUND)
        try:
            removed = oidc_accounts.unlink(s, user.id, entry.id)
        except OidcError as exc:
            raise error(exc.code, exc.message, status.HTTP_409_CONFLICT) from exc
        if not removed:
            raise error("not_found", "This account is not linked to that provider.", status.HTTP_404_NOT_FOUND)


@router.delete("/oidc/admin/accounts/{account_id}/links/{provider_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Administrator: unlink an account from a provider (with the own password)")
def operator_unlink(
    account_id: Annotated[int, Path(ge=1)],
    provider_id: Annotated[int, Path(ge=1)],
    payload: PasswordIn,
    request: Request,
    admin: AdminUser,
) -> None:
    refuse_at_home(request)
    sender = _sender(request)
    try:
        login_guard.check(sender, admin.username)
    except login_guard.TooManyAttempts:
        raise error("too_many_attempts", "Too many attempts. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS) from None
    if not has_usable_password(admin.password_hash) or not verify_password(payload.password, admin.password_hash):
        login_guard.failed(sender, admin.username)
        raise error("bad_credentials", "The password is wrong.", status.HTTP_403_FORBIDDEN)
    login_guard.succeeded(sender, admin.username)
    with store() as s:
        entry = s.get_provider(provider_id)
        target = s.db.get(User, account_id)
        if target is None or entry is None:
            raise error("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        try:
            removed = oidc_accounts.unlink(s, account_id, provider_id)
        except OidcError as exc:
            raise error(exc.code, exc.message, status.HTTP_409_CONFLICT) from exc
        if not removed:
            raise error("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
        name = target.username
    logger.warning("OIDC link to provider %s removed by the administrator name=%s by=%s", entry.slug, name,
                   admin.username)


# --- authentik ---------------------------------------------------------------------------------------------------


@router.post("/oidc/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup(payload: SetupIn, admin: AdminUser, request: Request) -> dict[str, Any]:
    """⚠️ The token is used for this run only: not stored, not logged, not echoed. Always 200 with the steps."""
    refuse_at_home(request)
    logger.info("authentik setup started by=%s", admin.username)
    with store() as s:
        result = await authentik.setup(
            s,
            payload.url,
            payload.token,
            _base(request),
            confirm_issuer_change=payload.confirm_issuer_change,
            public_url=payload.public_url,
            headers=request.headers,
        )
    return result.as_dict()


@router.get("/oidc/authentik/address", summary="The public address, what the server sees and what authentik knows")
def authentik_address(_admin: AdminUser, request: Request) -> dict[str, Any]:
    with store() as s:
        return authentik.address_view(s, _base(request), request.headers)


def public_url_change_error(question: dict[str, Any]) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={
        "code": "public_url_change", "message": "The address changes the redirect address of providers.", **question,
    })


@router.post("/oidc/authentik/address", summary="Save the public address (\"Use it only\"); asks first on a change")
def authentik_save_address(payload: AddressIn, admin: AdminUser, request: Request) -> dict[str, Any]:
    with store() as s:
        try:
            view = authentik.save_public_url(s, payload.public_url, _base(request), confirm=payload.confirm)
        except ValueError as exc:
            raise error("public_url_invalid", "This is not a public address.", status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
        except authentik.PublicUrlChange as asked:
            raise public_url_change_error(asked.question) from asked
        except authentik.PublicUrlNotKept as exc:
            raise error("public_url_needed", "The address could not be saved.", status.HTTP_409_CONFLICT) from exc
    logger.info("Public address saved by=%s", admin.username)
    return view


@router.get("/oidc/authentik/blueprint", summary="Download a blueprint that creates the same objects in authentik")
def authentik_blueprint(_admin: AdminUser, request: Request) -> Response:
    with store() as s:
        try:
            text = authentik.blueprint(authentik.blueprint_redirect(s, _base(request)))
        except authentik.PublicUrlNeeded as exc:
            raise error("public_url_needed", "Set the public address first.", status.HTTP_409_CONFLICT) from exc
    return Response(content=text, media_type="application/yaml",
                    headers={"Content-Disposition": f'attachment; filename="{authentik.blueprint_filename()}"'})
