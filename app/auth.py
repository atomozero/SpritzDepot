"""Email + password auth with JWT bearer tokens.

Prototype-grade but real: bcrypt hashing, short-lived JWTs with a per-user
version for revocation. SECRET_KEY comes from app.config (env-driven, prod-gated).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlmodel import Session

from .config import SECRET_KEY
from .db import get_session
from .models import User

ALGORITHM = "HS256"
# Short-lived access tokens: a stolen token is useful for hours, not a week.
# Pair with revocation (token_version) for explicit invalidation.
TOKEN_TTL_MINUTES = 60 * 2  # 2 hours

# Minimum password length enforced at register / change time. 12 is the modern
# floor: with a public registration and only a per-IP rate limit, length is the
# main brute-force defense.
MIN_PASSWORD_LENGTH = 12

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Claims that MUST be present for a token to be accepted. Absence fails closed:
# a token without exp would never expire, one without ver would bypass the
# token_version revocation check (both were latent fail-open with .get defaults).
_REQUIRED_CLAIMS = {"require_exp": True, "require_sub": True,
                    "require": ["exp", "sub", "ver"]}


def hash_password(plain: str) -> str:
    # bcrypt caps input at 72 bytes; encode and let bcrypt handle the salt.
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


# A fixed bcrypt hash to verify against when a login email is unknown, so the
# "no such user" path spends the same ~bcrypt time as the "wrong password" path
# and cannot be timed to enumerate registered emails. Computed once at import.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"spritz-timing-equalizer",
                                    bcrypt.gensalt()).decode("utf-8")


def make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "ver": user.token_version,   # invalidated when the user bumps this
        "exp": datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def current_user(
    token: str = Depends(oauth2),
    session: Session = Depends(get_session),
) -> User:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM],
                             options=_REQUIRED_CLAIMS)
        user_id = int(payload["sub"])
        token_ver = int(payload["ver"])   # required claim; KeyError -> 401
    except (JWTError, TypeError, ValueError, KeyError):
        raise creds_error
    user = session.get(User, user_id)
    if user is None or token_ver != user.token_version:
        # Stale version means the token was revoked (logout-everywhere, password
        # change, or compromise). Reject it.
        raise creds_error
    return user
