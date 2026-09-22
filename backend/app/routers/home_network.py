"""Signed in on the home network: the sign-in page's side and the administrator's.

The rules are in ``services/home_network.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import CSRF_HEADER, AdminUser, DbSession, error
from ..models import Session, User
from ..schemas import UserPublic
from ..services import home_network

router = APIRouter(prefix="/api/v1", tags=["auth"])
logger = logging.getLogger("nexdeck.auth")

#: Why a browser is not signed in at home, in words for the administrator.
REASONS = {
    "off": "Signing in on the home network is switched off.",
    "outside": "This address is outside the home networks.",
    "direct": "Seen directly, without a proxy in between.",
    "via_proxy": "Seen through a proxy named in NEXDECK_TRUSTED_PROXIES.",
    "forwarded_by_unknown": "Something in front of nexdeck forwards this request for somebody else, and it is not named in NEXDECK_TRUSTED_PROXIES, so the real address is unknown.",
    "proxy_without_forwarding": "The proxy in front of nexdeck says nothing about whom it forwards for.",
    "unreadable_forwarding": "The proxy's forwarding header could not be read.",
    "no_peer": "The connection carries no address.",
    "no_account": "The chosen account is missing, disabled or an administrator.",
    "factor_required": "Every account owes a second factor on this installation.",
    "home": "At home.",
}


class HomeSignIn(BaseModel):
    #: From the button on the sign-in page after signing out on purpose.
    again: bool = False


class HomeSettingsBody(BaseModel):
    enabled: bool = False
    networks: list[str] = Field(default_factory=list, max_length=20)
    user_id: int | None = None


@router.get("/auth/home", summary="Whether this browser is signed in on the home network without a password")
def home_state(request: Request, db: DbSession) -> dict:
    """For the sign-in page. Outside the home networks it says no and nothing more."""
    user, _ = home_network.account_for(db, request)
    if user is None:
        return {"available": False}
    return {"available": True, "held_off": bool(request.cookies.get(home_network.OFF_COOKIE)),
            "name": user.display_name or user.username}


@router.post("/auth/home", response_model=UserPublic, summary="Sign in on the home network without a password")
def home_sign_in(body: HomeSignIn, request: Request, response: Response, db: DbSession) -> UserPublic:
    from .auth import open_session, user_public

    # A form on another site could otherwise sign this browser in as the
    # shared account behind the owner's back.
    if request.headers.get(CSRF_HEADER) != "1":
        raise error("csrf", "This request must come from the nexdeck app.", status.HTTP_403_FORBIDDEN)
    user, why = home_network.account_for(db, request)
    if user is None:
        raise error("not_at_home", REASONS.get(why, "Not on the home network."), status.HTTP_401_UNAUTHORIZED)
    if request.cookies.get(home_network.OFF_COOKIE) and not body.again:
        raise error("held_off", "Signed out on purpose; sign in again from the sign-in page.", status.HTTP_401_UNAUTHORIZED)
    address, _ = home_network.seen_address(request)
    open_session(db, user, request, response, kind=home_network.KIND, address=address or "")
    response.delete_cookie(home_network.OFF_COOKIE, path="/", httponly=True)
    logger.info("%s signed in on the home network from %s, without a password.", user.username, address)
    request.state.auth_kind = "home"
    return user_public(user, request)


@router.get("/settings/home-network", summary="The home-network sign-in, for the administrator")
def home_settings(request: Request, user: AdminUser, db: DbSession) -> dict:
    settings = home_network.load(db)
    address, how = home_network.seen_address(request)
    recent = db.execute(
        select(Session, User.username).join(User, User.id == Session.user_id)
        .where(Session.kind == home_network.KIND).order_by(Session.created_at.desc()).limit(8)
    ).all()
    return {
        **settings.view(),
        # What nexdeck makes of the administrator's own request: the quickest
        # way to see whether a proxy in front hides the real addresses.
        "seen": {"address": address, "how": how, "reason": REASONS.get(how, how)},
        "trusted_proxies": [str(n) for n in home_network.trusted_proxies()],
        "recent": [{"username": name, "address": row.address, "at": row.created_at.isoformat(), "active": not row.revoked,
                    "user_agent": row.user_agent} for row, name in recent],
    }


@router.put("/settings/home-network", summary="Change the home-network sign-in")
def put_home_settings(body: HomeSettingsBody, request: Request, user: AdminUser, db: DbSession) -> dict:
    try:
        kept = home_network.store(db, home_network.Settings(body.enabled, tuple(body.networks), body.user_id))
    except home_network.Refused as refused:
        raise error("home_network_refused", str(refused)) from refused
    db.commit()
    logger.info("Signing in on the home network %s by %s (%s).", "switched on" if kept.enabled else "switched off",
                user.username, ", ".join(kept.networks) or "no networks")
    return home_settings(request, user, db)
