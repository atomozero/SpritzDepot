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

# Minimum password length enforced at register / change time.
MIN_PASSWORD_LENGTH = 8

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    # bcrypt caps input at 72 bytes; encode and let bcrypt handle the salt.
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        token_ver = int(payload.get("ver", 0))
    except (JWTError, TypeError, ValueError):
        raise creds_error
    user = session.get(User, user_id)
    if user is None or token_ver != user.token_version:
        # Stale version means the token was revoked (logout-everywhere, password
        # change, or compromise). Reject it.
        raise creds_error
    return user
