"""Personal API tokens."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from ..deps import CurrentUser, DbSession, MemberUser, error
from ..models import ApiToken
from ..schemas import TokenCreate
from ..security import new_opaque_token

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])


def _public(token: ApiToken) -> dict:
    return {"id": token.id, "name": token.name, "prefix": token.prefix, "created_at": token.created_at, "last_used_at": token.last_used_at}


@router.get("", summary="List my API tokens")
def list_tokens(user: CurrentUser, db: DbSession) -> list[dict]:
    return [_public(t) for t in db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id))]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an API token")
def create_token(body: TokenCreate, user: MemberUser, db: DbSession) -> dict:
    """The token is shown once. It carries the same rights as the account."""
    token, token_hash, prefix = new_opaque_token("nd")
    row = ApiToken(user_id=user.id, name=body.name.strip(), token_hash=token_hash, prefix=prefix)
    db.add(row)
    db.commit()
    return {**_public(row), "token": token}


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API token")
def delete_token(token_id: int, user: CurrentUser, db: DbSession) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise error("not_found", "There is no such token.", status.HTTP_404_NOT_FOUND)
    db.delete(row)
    db.commit()
