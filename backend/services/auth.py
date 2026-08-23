"""Sign-in for the private side of the site.

One deliberate split runs through this module: **a shared report link stays
public.** Sharing a brief is the point of the product, and a login wall in
front of /r/{key} would break the one thing people are meant to do with a
finished report. Everything that spends quota or exposes operational detail
sits behind the session.

No accounts table yet. There is one operator, the password lives in the
environment, and the session is a signed cookie — the same trust model as the
admin token, which is already in production. When there are real users this
grows a table; nothing here assumes there will only ever be one.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request

from backend.config import settings

COOKIE_NAME = "scout_session"
# Long enough not to be a nuisance, short enough that a borrowed laptop does
# not stay signed in indefinitely.
SESSION_MAX_AGE = 14 * 24 * 3600


def _secret() -> bytes:
    """The key that signs sessions.

    Falls back to a per-process random value when unset, which is safe but
    means every restart signs people out — and Render restarts often. The
    fallback is announced at start-up rather than left to be discovered.
    """
    if settings.session_secret:
        return settings.session_secret.encode()
    return _EPHEMERAL


_EPHEMERAL = secrets.token_bytes(32)


def is_enabled() -> bool:
    """Sign-in only applies once a password exists.

    Unset, the site behaves exactly as it does today. That keeps local
    development usable and means deploying this code cannot lock anybody out
    of their own site by accident.
    """
    return bool(settings.auth_password)


def _sign(payload: bytes) -> str:
    mac = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=")
            + "."
            + base64.urlsafe_b64encode(mac).decode().rstrip("="))


def _unpad(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(email: str) -> str:
    payload = json.dumps({"e": email, "t": int(time.time())}).encode()
    return _sign(payload)


def verify(token: str | None) -> dict | None:
    """The session this cookie represents, or None if it is not ours."""
    if not token or "." not in token:
        return None
    raw, _, mac = token.partition(".")
    try:
        payload = _unpad(raw)
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        # Constant-time: a plain != leaks the signature a byte at a time to
        # anyone patient enough to measure.
        if not hmac.compare_digest(_unpad(mac), expected):
            return None
        data = json.loads(payload)
    except Exception:
        return None

    if time.time() - data.get("t", 0) > SESSION_MAX_AGE:
        return None
    return data


def check_password(supplied: str) -> bool:
    if not settings.auth_password:
        return False
    return hmac.compare_digest(supplied, settings.auth_password)


def current_user(request: Request) -> dict | None:
    return verify(request.cookies.get(COOKIE_NAME))


def is_signed_in(request: Request) -> bool:
    """Signed in, or sign-in is switched off entirely."""
    if not is_enabled():
        return True
    return current_user(request) is not None
