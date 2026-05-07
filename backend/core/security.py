from datetime import datetime, timedelta, timezone
import base64
import hashlib
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import HTTPException, status
from core.config import settings

def _normalize_password(password: str) -> str:
    """
    bcrypt only accepts up to 72 bytes; pre-hash oversized passwords so we can
    support long passphrases without truncation.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) <= 72:
        return password
    digest = hashlib.sha256(password_bytes).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_password(password: str) -> str:
    normalized = _normalize_password(password).encode("utf-8")
    return bcrypt.hashpw(normalized, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            _normalize_password(plain).encode("utf-8"),
            hashed.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict = {}) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, "type": "access", **extra}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, token_type: str = "access") -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != token_type:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception
