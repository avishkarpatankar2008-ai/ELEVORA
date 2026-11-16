from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Cookie, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.core.rate_limit import enforce_user_rate_limit
from app.core.security import decode_access_token_claims
from app.database import get_database

settings = get_settings()


async def get_current_user(
    db: AsyncIOMotorDatabase = Depends(get_database),
    session_token: str | None = Cookie(default=None, alias=settings.cookie_name),
) -> dict[str, Any]:
    """Resolve the logged-in user from the HTTP-only session cookie.

    Raises 401 for any failure mode (missing cookie, bad/expired token,
    or a user that no longer exists) so callers can't distinguish these -
    that avoids leaking which part of auth failed.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )

    if not session_token:
        raise credentials_error

    claims = decode_access_token_claims(session_token)
    if not claims:
        raise credentials_error
    user_id = claims["sub"]

    # Logout revokes the token's id server-side; a copied cookie stops working.
    if await db.revoked_tokens.find_one({"jti": claims["jti"]}, {"_id": 1}):
        raise credentials_error

    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        raise credentials_error

    user = await db.users.find_one({"_id": object_id})
    if not user:
        raise credentials_error

    return user


def user_rate_limit(scope: str):
    """Dependency factory: per-user throttle for endpoints that spend AI/CPU budget.

    Runs after authentication, so the key is the user id, not an IP that many
    users may share (offices, mobile carriers, the frontend proxy). The count is
    shared across worker processes through MongoDB (see core/rate_limit.py).
    """

    async def _limit(
        current_user: dict = Depends(get_current_user),
        db: AsyncIOMotorDatabase = Depends(get_database),
    ) -> dict:
        wait_seconds = await enforce_user_rate_limit(db, scope, str(current_user["_id"]))
        if wait_seconds > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="You're doing that too quickly. Please wait a moment and try again.",
                headers={"Retry-After": str(max(1, int(wait_seconds)))},
            )
        return current_user

    return _limit
