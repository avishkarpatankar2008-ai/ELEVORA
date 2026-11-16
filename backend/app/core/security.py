"""Password hashing and JWT session tokens."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from app.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A pre-computed bcrypt hash of a random string, used to keep the login
# endpoint's timing roughly constant when the email doesn't exist. Without
# this, "no such user" returns measurably faster than "wrong password", which
# leaks account existence.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.gIhSRUcHnXb9u/1C1UPqkVhFSPKQCXe"

TOKEN_TYPE = "access"


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Never raises: a malformed/unknown stored hash is a failed verification."""
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except (UnknownHashError, ValueError):
        return False


def verify_dummy_password(plain_password: str) -> None:
    """Burn the same amount of CPU as a real verification. Call it whenever a
    login attempt targets an account that doesn't exist."""
    try:
        _pwd_context.verify(plain_password, _DUMMY_HASH)
    except (UnknownHashError, ValueError):
        pass


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """Create a signed JWT whose subject ("sub") is the user's id."""
    now = datetime.now(timezone.utc)
    minutes = settings.access_token_expire_minutes if expires_minutes is None else expires_minutes
    expire = now + timedelta(minutes=minutes)
    payload = {
        "sub": subject,
        "type": TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token_claims(token: str) -> dict | None:
    """Return the verified claims of an access token, or None if the token is
    invalid, expired, not an access token, or lacks a subject / token id."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.PyJWTError:
        return None

    if payload.get("type") != TOKEN_TYPE:
        return None
    subject = payload.get("sub")
    token_id = payload.get("jti")
    if not (isinstance(subject, str) and subject and isinstance(token_id, str) and token_id):
        return None
    return payload


def decode_access_token(token: str) -> str | None:
    """Return the user id encoded in the token, or None if the token is
    invalid, expired, or not an access token."""
    claims = decode_access_token_claims(token)
    return claims["sub"] if claims else None
