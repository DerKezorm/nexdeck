"""Sign in, sign out, the own profile and sessions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import COOKIE_NAME, CurrentUser, DbSession, error
from ..models import Notice, OidcProvider, Session, User, utcnow
from ..schemas import (
    LoginBody,
    MePatch,
    PasswordBody,
    ResetBody,
    ResetRequest,
    SecondStepBody,
    TwoFactorConfirm,
    TwoFactorOff,
    UserPublic,
)
from ..security import (
    burn_a_password_check,
    create_session_token,
    create_step_token,
    has_usable_password,
    hash_password,
    now_ms,
    read_step_token,
    verify_password,
)
from ..services import avatars, login_guard, mail, password_reset, two_factor
from ..uploads import read_at_most

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger("nexdeck.auth")


def cookie_secure(request: Request) -> bool:
    mode = get_settings().cookie_secure
    if mode == "always":
        return True
    if mode == "never":
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.session_days * 86400, path=settings.url_base or "/",
        httponly=True, samesite="lax", secure=cookie_secure(request),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=get_settings().url_base or "/", httponly=True)


def user_public(user: User, request: Request | None = None) -> UserPublic:
    return UserPublic(
        id=user.id, username=user.username, display_name=user.display_name or user.username, role=user.role,
        locale=user.locale, theme=user.theme, start_board_id=user.start_board_id, disabled=user.disabled,
        seen_version=user.seen_version, has_password=has_usable_password(user.password_hash),
        auth_kind=getattr(request.state, "auth_kind", "session") if request is not None else "session",
        avatar_url=avatars.url_for(user.avatar),
        email=user.email,
    )


def open_session(db: DbSession, user: User, request: Request, response: Response) -> None:
    session = Session(user_id=user.id, user_agent=request.headers.get("user-agent", "")[:300])
    db.add(session)
    db.commit()
    set_session_cookie(response, request, create_session_token(user.id, session.id))


@router.post("/login", response_model=UserPublic, summary="Sign in with user name and password")
def login(body: LoginBody, request: Request, response: Response, db: DbSession) -> UserPublic:
    """Opens a browser session. Wrong attempts are throttled per address."""
    address = request.client.host if request.client else "?"
    try:
        # Counted per address and per account: the address can be spoofed
        # behind a proxy, the account name cannot.
        login_guard.check(address, body.username)
    except login_guard.TooManyAttempts:
        raise error(
            "too_many_attempts",
            "Too many failed sign-ins. Try again in a few minutes.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        ) from None
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    # ⚠️ Hash something either way. Checking a password costs about 300 ms at
    # twelve rounds and a missing account cost nothing, so the answer time
    # said whether a name exists on this installation. The throttle counts
    # attempts, it does not hide that difference.
    right = verify_password(body.password, user.password_hash) if user is not None else burn_a_password_check(body.password)
    if user is None or user.disabled or not right:
        login_guard.failed(address, body.username)
        logger.info("Sign-in refused for %r from %s.", body.username, address)
        raise error("bad_credentials", "User name or password is wrong.", status.HTTP_401_UNAUTHORIZED)
    login_guard.succeeded(address, body.username)
    if two_factor.enabled(user):
        # ⚠️ No session yet. The ticket says the password was right and can be
        # exchanged for a session only together with a code; on its own it
        # opens nothing.
        logger.info("%s gave the right password from %s and now needs a code.", user.username, address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "second_step",
                "message": "Enter the code from your authenticator app.",
                "ticket": create_step_token(user.id),
                "recovery": two_factor.codes_left(user) > 0,
            },
        )
    open_session(db, user, request, response)
    logger.info("%s signed in from %s.", user.username, address)
    if two_factor.must_set_up(db, user):
        # Signed in, but the installation wants a factor before anything else.
        logger.info("%s is being asked to set up a second factor.", user.username)
    return user_public(user, request)


#: Where the OIDC return path leaves its half-finished sign-in.
STEP_COOKIE = "nexdeck_step"
STEP_MINUTES = 10


@router.post("/login/second-step", response_model=UserPublic, summary="Finish a sign-in with the second factor")
def second_step(body: SecondStepBody, request: Request, response: Response, db: DbSession) -> UserPublic:
    """The other half: the ticket from the first step, plus a code.

    Throttled like the first step, and per account, because the ticket already
    says which account it is: without that, six digits are guessable.
    """
    address = request.client.host if request.client else "?"
    # The password path puts the ticket in the body; the OIDC path cannot,
    # because it arrives as a redirect, so it leaves it in a cookie.
    claims = read_step_token(body.ticket or request.cookies.get(STEP_COOKIE, ""))
    if claims is None:
        raise error("bad_ticket", "That sign-in took too long. Start again.", status.HTTP_401_UNAUTHORIZED)
    user_id, issued_ms = claims
    user = db.get(User, user_id)
    if user is None or user.disabled or issued_ms < user.password_changed_ms:
        raise error("bad_ticket", "That sign-in took too long. Start again.", status.HTTP_401_UNAUTHORIZED)

    try:
        login_guard.check(address, f"2fa:{user.username}")
    except login_guard.TooManyAttempts:
        raise error(
            "too_many_attempts", "Too many wrong codes. Try again in a few minutes.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        ) from None

    used_recovery = False
    if body.recovery_code.strip():
        used_recovery = two_factor.use_code(db, user, body.recovery_code)
        ok = used_recovery
    else:
        ok = two_factor.check_code(db, user, body.code)
    if not ok:
        login_guard.failed(address, f"2fa:{user.username}")
        logger.info("A wrong second factor for %s from %s.", user.username, address)
        raise error("bad_code", "That code is not right.", status.HTTP_401_UNAUTHORIZED)

    login_guard.succeeded(address, f"2fa:{user.username}")
    open_session(db, user, request, response)
    left = two_factor.codes_left(user)
    logger.info("%s signed in from %s with %s.", user.username, address,
                f"a recovery code, {left} left" if used_recovery else "a code")
    return user_public(user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    from ..security import read_session_token

    raw = request.cookies.get(COOKIE_NAME)
    claims = read_session_token(raw) if raw else None
    if claims is not None:
        session = db.get(Session, claims.session_id)
        if session is not None:
            session.revoked = True
            db.commit()
            logger.info("A browser session was signed out.")
    clear_session_cookie(response)


def own_address(db: DbSession, user: User, value: str) -> str:
    """Check an address before it is stored. An empty one clears the field.

    Unique across accounts, because a password reset has to end at exactly one
    of them; without that rule the address would name two people.
    """
    address = value.strip()
    if not address:
        return ""
    if not mail.valid_address(address):
        raise error("bad_address", "That does not look like an e-mail address.")
    taken = db.scalar(select(User).where(func.lower(User.email) == address.lower(), User.id != user.id))
    if taken is not None:
        raise error("taken", "Another account already uses that address.", status.HTTP_409_CONFLICT)
    return address


@router.get("/me", response_model=UserPublic, summary="Who am I")
def me(user: CurrentUser, request: Request) -> UserPublic:
    return user_public(user, request)


@router.patch("/me", response_model=UserPublic, summary="Change own profile settings")
def patch_me(body: MePatch, user: CurrentUser, request: Request, db: DbSession) -> UserPublic:
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.email is not None:
        user.email = own_address(db, user, body.email)
    if body.locale is not None:
        user.locale = body.locale
    if body.theme is not None:
        user.theme = body.theme
    if body.start_board_id is not None:
        user.start_board_id = body.start_board_id or None
    if body.seen_version is not None:
        user.seen_version = body.seen_version
    db.commit()
    return user_public(user, request)


@router.post("/me/avatar", response_model=UserPublic, summary="Upload own profile picture")
async def upload_avatar(file: UploadFile, user: CurrentUser, request: Request, db: DbSession) -> UserPublic:
    """Replaces the picture that was there; the old file is deleted."""
    data = await read_at_most(file, avatars.MAX_BYTES, "picture")
    try:
        user.avatar = avatars.save(data, user.avatar)
    except avatars.AvatarError as failure:
        raise error(failure.code, failure.message) from failure
    db.commit()
    return user_public(user, request)


@router.delete("/me/avatar", response_model=UserPublic, summary="Remove own profile picture")
def delete_avatar(user: CurrentUser, request: Request, db: DbSession) -> UserPublic:
    avatars.remove(user.avatar)
    user.avatar = ""
    db.commit()
    return user_public(user, request)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change own password")
def change_password(body: PasswordBody, user: CurrentUser, db: DbSession) -> None:
    """Every session of the account is signed out afterwards, this one included.

    ⚠️ Deliberate, and a test says so. What was missing is that the interface
    never noticed: the cookie was issued before ``password_changed_ms`` and
    the next request simply came back 401, so the person who had just changed
    their password watched the app go blank. The saying-so happens in the
    frontend, not here.
    """
    if has_usable_password(user.password_hash) and not verify_password(body.current_password, user.password_hash):
        raise error("bad_credentials", "The current password is wrong.", status.HTTP_403_FORBIDDEN)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_ms = now_ms()
    db.commit()
    # Worth a line of its own: it ends every other session and every API token
    # of the account, which is what somebody reads this log to find out.
    logger.info("%s changed their password; every other session and token of the account ends here.", user.username)


@router.get("/sessions", summary="List own browser sessions")
def sessions(user: CurrentUser, db: DbSession) -> list[dict]:
    rows = db.scalars(select(Session).where(Session.user_id == user.id, Session.revoked.is_(False)).order_by(Session.last_seen_at.desc()))
    return [{"id": s.id, "user_agent": s.user_agent, "created_at": s.created_at, "last_seen_at": s.last_seen_at} for s in rows]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out another session")
def revoke_session(session_id: int, user: CurrentUser, db: DbSession) -> None:
    session = db.get(Session, session_id)
    if session is None or session.user_id != user.id:
        raise error("not_found", "There is no such session.", status.HTTP_404_NOT_FOUND)
    session.revoked = True
    db.commit()
    logger.info("%s signed another of their browser sessions out.", user.username)


@router.get("/unread", summary="Count unread notices")
def unread(user: CurrentUser, db: DbSession) -> dict:
    count = db.scalar(select(func.count(Notice.id)).where(Notice.user_id == user.id, Notice.read_at.is_(None))) or 0
    return {"unread": int(count), "now": datetime.now(UTC).isoformat()}


@router.get("/providers", summary="List sign-in providers")
def providers(db: DbSession) -> list[dict]:
    """Public: the buttons on the sign-in page."""
    rows = db.scalars(select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.id))
    return [{"slug": p.slug, "label": p.label} for p in rows]


def utc_now_iso() -> str:
    return utcnow().isoformat()


# ---------------------------------------------------------------------------
# The second factor, from the owner's side
# ---------------------------------------------------------------------------


@router.get("/two-factor", summary="Whether this account has a second factor")
def two_factor_state(user: CurrentUser, db: DbSession) -> dict:
    return {
        "enabled": two_factor.enabled(user),
        "recovery_codes_left": two_factor.codes_left(user),
        "required_by_operator": two_factor.required(db),
    }


@router.post("/two-factor/start", summary="Begin setting up a second factor")
def two_factor_start(user: CurrentUser, db: DbSession) -> dict:
    """Hands out a fresh secret and the QR code that carries it.

    ⚠️ Nothing is switched on here. The secret is stored unconfirmed, and only
    a code that it produced turns it on, so a setup somebody abandoned halfway
    cannot lock them out.
    """
    if two_factor.enabled(user):
        raise error("already_on", "This account already has a second factor.", status.HTTP_409_CONFLICT)
    secret = two_factor.new_secret()
    two_factor.store_secret(user, secret)
    db.commit()
    url = two_factor.otpauth_url(user, secret)
    logger.info("%s started setting up a second factor.", user.username)
    return {"secret": secret, "otpauth_url": url, "qr_svg": two_factor.qr_svg(url)}


@router.post("/two-factor/confirm", summary="Switch the second factor on with a code")
def two_factor_confirm(body: TwoFactorConfirm, user: CurrentUser, db: DbSession) -> dict:
    """The recovery codes come back here, in the clear, exactly once."""
    if two_factor.enabled(user):
        raise error("already_on", "This account already has a second factor.", status.HTTP_409_CONFLICT)
    if not user.totp_secret:
        raise error("not_started", "Start the setup first.", status.HTTP_409_CONFLICT)
    if not two_factor.check_code(db, user, body.code):
        raise error("bad_code", "That code is not right. Check the time on the phone as well.", status.HTTP_400_BAD_REQUEST)
    user.totp_confirmed = True
    db.commit()
    codes = two_factor.new_codes(db, user)
    logger.info("%s switched a second factor on.", user.username)
    return {"enabled": True, "recovery_codes": codes}


@router.post("/two-factor/recovery-codes", summary="Replace the recovery codes")
def two_factor_recovery(body: TwoFactorOff, user: CurrentUser, db: DbSession) -> dict:
    """Fresh codes, shown once. The old ones stop working immediately."""
    if not two_factor.enabled(user):
        raise error("not_on", "This account has no second factor.", status.HTTP_409_CONFLICT)
    _prove_it_is_you(db, user, body.password, body.code)
    return {"recovery_codes": two_factor.new_codes(db, user)}


def _prove_it_is_you(db: DbSession, user: User, password: str, code: str) -> None:
    """The password, or a current code where there is no password.

    ⚠️ Both undoings of a second factor used to ask for the password only when
    the account had one. An account created through OpenID Connect never does.
    """
    if has_usable_password(user.password_hash):
        if not verify_password(password, user.password_hash):
            raise error("bad_credentials", "The password is wrong.", status.HTTP_403_FORBIDDEN)
        return
    if not two_factor.check_code(db, user, code):
        raise error(
            "bad_code",
            "This account has no password, so it takes a current code from the authenticator app.",
            status.HTTP_403_FORBIDDEN,
        )


@router.delete("/two-factor", status_code=status.HTTP_204_NO_CONTENT, summary="Switch the second factor off")
def two_factor_disable(body: TwoFactorOff, user: CurrentUser, db: DbSession) -> None:
    """⚠️ An account without a password proves itself with a code instead.

    The check used to sit behind ``has_usable_password``, and an account that
    signed in through OpenID Connect has never had one. For those the whole
    condition fell away, so anybody holding an open session could switch the
    second factor off without proving anything at all, which is the opposite
    of what a second factor is for.
    """
    _prove_it_is_you(db, user, body.password, body.code)
    if two_factor.required(db):
        raise error(
            "required_by_operator",
            "A second factor is required for every account on this installation.",
            status.HTTP_409_CONFLICT,
        )
    two_factor.turn_off(db, user)


# ---------------------------------------------------------------------------
# Forgotten passwords
# ---------------------------------------------------------------------------


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED, summary="Ask for a link to set a new password")
def forgot(body: ResetRequest, request: Request, db: DbSession) -> dict:
    """Always the same answer.

    ⚠️ Whether the name exists, whether the account carries an address,
    whether the mail went out: identical. Anything else turns this into a list
    of who has an account here.
    """
    address = request.client.host if request.client else "?"
    try:
        # Counted like a sign-in: this sends mail, and somebody who can send
        # a hundred of them can fill an inbox.
        login_guard.check(address, f"forgot:{body.username.lower()}")
    except login_guard.TooManyAttempts:
        raise error(
            "too_many_attempts", "Too many attempts. Try again in a few minutes.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        ) from None
    login_guard.failed(address, f"forgot:{body.username.lower()}")
    password_reset.request(db, body.username)
    return {"sent": True}


@router.get("/reset/{token}", summary="Whether a reset link is still good")
def reset_state(token: str, db: DbSession) -> dict:
    user = password_reset.holder(db, token)
    return {"valid": user is not None, "username": user.username if user else ""}


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT, summary="Set a new password with a reset link")
def reset(body: ResetBody, db: DbSession) -> None:
    if not password_reset.redeem(db, body.token, body.new_password):
        raise error(
            "bad_token",
            "That link is used up or too old. Ask for a new one.",
            status.HTTP_400_BAD_REQUEST,
        )
