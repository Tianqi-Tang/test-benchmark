from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

from fastapi import Cookie, HTTPException, Response, status


AUTH_COOKIE_NAME = "test_benchmark_session"
AUTH_MAX_AGE_SECONDS = 60 * 60 * 12


def auth_configured() -> bool:
    return bool(_auth_password())


def login(password: str, response: Response) -> None:
    expected = _auth_password()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication password is not configured.")
    if not secrets.compare_digest(password, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password.")
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=_create_token(),
        max_age=AUTH_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        path="/",
    )


def logout(response: Response) -> None:
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/", samesite="lax", secure=_secure_cookie())


def require_session(session_token: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> None:
    if not auth_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication password is not configured.")
    if not session_token or not _verify_token(session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")


def session_is_active(session_token: Optional[str]) -> bool:
    return auth_configured() and bool(session_token) and _verify_token(session_token)


def _auth_password() -> str:
    return os.getenv("TEST_BENCHMARK_AUTH_PASSWORD", "").strip()


def _auth_secret() -> bytes:
    configured = os.getenv("TEST_BENCHMARK_AUTH_SECRET", "").strip()
    secret = configured or _auth_password()
    return secret.encode("utf-8")


def _secure_cookie() -> bool:
    return os.getenv("TEST_BENCHMARK_AUTH_SECURE_COOKIE", "").strip().lower() in {"1", "true", "yes"}


def _create_token() -> str:
    issued_at = int(time.time())
    payload = {
        "iat": issued_at,
        "exp": issued_at + AUTH_MAX_AGE_SECONDS,
        "nonce": secrets.token_urlsafe(16),
    }
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_encoded = _b64encode(payload_text.encode("utf-8"))
    signature = _sign(payload_encoded)
    return f"{payload_encoded}.{signature}"


def _verify_token(token: str) -> bool:
    try:
        payload_encoded, signature = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(payload_encoded), signature):
        return False
    try:
        payload = json.loads(_b64decode(payload_encoded))
    except (ValueError, json.JSONDecodeError):
        return False
    return _payload_is_valid(payload)


def _payload_is_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    exp = payload.get("exp")
    return isinstance(exp, int) and exp > int(time.time())


def _sign(payload_encoded: str) -> str:
    digest = hmac.new(_auth_secret(), payload_encoded.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")
