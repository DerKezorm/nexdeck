"""Personal API tokens."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, MemberUser, error
from ..models import ApiToken, utcnow
from ..schemas import TokenCreate
from ..security import new_opaque_token

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])

logger = logging.getLogger("nexdeck.tokens")


def _public(token: ApiToken) -> dict:
    return {"id": token.id, "name": token.name, "prefix": token.prefix, "created_at": token.created_at,
            "last_used_at": token.last_used_at, "expires_at": token.expires_at}


@router.get("", summary="List my API tokens")
def list_tokens(user: CurrentUser, db: DbSession) -> list[dict]:
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id))
    return [_public(t) for t in rows if not t.revoked]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an API token")
def create_token(body: TokenCreate, user: MemberUser, db: DbSession) -> dict:
    """The token is shown once. It carries the same rights as the account.

    It also ends when the password changes, like every session does.
    """
    token, token_hash, prefix = new_opaque_token("nd")
    ends = utcnow() + timedelta(days=body.expires_days) if body.expires_days else None
    row = ApiToken(user_id=user.id, name=body.name.strip(), token_hash=token_hash, prefix=prefix, expires_at=ends)
    db.add(row)
    db.commit()
    logger.info("API token %r (%s) created for %s%s.", row.name, row.prefix, user.username,
                f", ending {ends:%Y-%m-%d}" if ends else ", with no end")
    return {**_public(row), "token": token}


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API token")
def delete_token(token_id: int, user: CurrentUser, db: DbSession) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.revoked or row.user_id != user.id:
        raise error("not_found", "There is no such token.", status.HTTP_404_NOT_FOUND)
    # The row stays so the same hash can never come back.
    row.revoked = True
    row.revoked_at = utcnow()
    db.commit()
    logger.info("API token %r (%s) of %s was withdrawn.", row.name, row.prefix, user.username)
