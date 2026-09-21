from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

try:
    from jose import jwt
    _IS_JOSE = True
except ImportError:
    import jwt
    _IS_JOSE = False

from core.config import settings

logger = logging.getLogger(__name__)

# Google public x509 certificates URL for Firebase Auth
GOOGLE_CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

_certs_cache: Dict[str, str] = {}
_certs_cache_expiry: float = 0.0


async def _get_google_public_certs() -> Dict[str, str]:
    """Fetch and cache Google's public x509 certificates (rotated periodically)."""
    global _certs_cache, _certs_cache_expiry
    now = time.time()
    if _certs_cache and now < _certs_cache_expiry:
        return _certs_cache

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(GOOGLE_CERTS_URL)
            if resp.status_code == 200:
                _certs_cache = resp.json()
                cc = resp.headers.get("cache-control", "")
                max_age = 3600
                for part in cc.split(","):
                    if "max-age=" in part:
                        try:
                            max_age = int(part.split("=")[1].strip())
                        except Exception:
                            pass
                _certs_cache_expiry = now + max_age
                return _certs_cache
    except Exception as exc:
        logger.warning("[FIREBASE] Failed to fetch Google x509 certs: %s", exc)

    return _certs_cache


async def verify_firebase_id_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Cryptographically verify a Firebase ID Token.
    Returns decoded claims dict with `uid`, `email`, `name` if valid, or None if invalid.
    """
    if not id_token or not isinstance(id_token, str):
        return None

    clean_token = id_token.strip()

    # 1. First attempt: Verify via Google OAuth2 TokenInfo endpoint (authoritative)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": clean_token})
            if resp.status_code == 200:
                data = resp.json()
                aud = data.get("aud")
                project_id = settings.FIREBASE_PROJECT_ID.strip() if settings.FIREBASE_PROJECT_ID else ""

                if project_id and aud != project_id:
                    logger.warning("[FIREBASE] Token audience mismatch: expected '%s', got '%s'", project_id, aud)
                    return None

                email = data.get("email")
                uid = data.get("sub") or data.get("user_id")
                if not email or not uid:
                    return None

                return {
                    "uid": str(uid),
                    "email": str(email).lower().strip(),
                    "name": data.get("name") or str(email).split("@")[0],
                    "picture": data.get("picture"),
                    "email_verified": data.get("email_verified") == "true" or data.get("email_verified") is True,
                }
            else:
                logger.debug("[FIREBASE] TokenInfo rejected token: status %d", resp.status_code)
    except Exception as exc:
        logger.debug("[FIREBASE] Google tokeninfo request error: %s", exc)

    # 2. Fallback attempt: Cryptographic signature verification using cached Google x509 certs
    try:
        unverified_header = jwt.get_unverified_header(clean_token)
        kid = unverified_header.get("kid")
        certs = await _get_google_public_certs()
        cert = certs.get(kid) if kid else None

        if cert:
            project_id = settings.FIREBASE_PROJECT_ID.strip() if settings.FIREBASE_PROJECT_ID else ""
            claims = jwt.decode(
                clean_token,
                cert,
                algorithms=["RS256"],
                audience=project_id if project_id else None,
                options={"verify_aud": bool(project_id)},
            )
            email = claims.get("email")
            uid = claims.get("sub") or claims.get("user_id")
            if email and uid:
                return {
                    "uid": str(uid),
                    "email": str(email).lower().strip(),
                    "name": claims.get("name") or str(email).split("@")[0],
                    "picture": claims.get("picture"),
                    "email_verified": bool(claims.get("email_verified", False)),
                }
    except Exception as exc:
        logger.debug("[FIREBASE] JWT cert verification failed: %s", exc)

    return None
