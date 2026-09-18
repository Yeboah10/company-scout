"""Password reset via a signed, time-limited token sent by email.

Uses the same signing infrastructure as the session cookie — no extra
database table, no new dependencies. The token encodes the email and
an expiry timestamp; it is verified by signature and by freshness.

The reset link is valid for one hour. After that the user must request
a new one, which is a better tradeoff than storing used tokens: a
one-hour window is too short to be worth exploiting, and the password
change itself invalidates any session the attacker might hold.
"""

import base64
import hashlib
import hmac
import json
import time

from backend.config import settings

TOKEN_MAX_AGE = 3600


def _secret() -> bytes:
    if settings.session_secret:
        return b"reset:" + settings.session_secret.encode()
    from backend.services.auth import _EPHEMERAL
    return b"reset:" + _EPHEMERAL


def issue(email: str) -> str:
    payload = json.dumps({
        "e": email.strip().lower(),
        "t": int(time.time()),
        "purpose": "reset",
    }).encode()
    mac = hmac.new(_secret(), payload, hashlib.sha256).digest()
    raw = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return f"{raw}.{sig}"


def verify(token: str) -> str | None:
    """Returns the email if the token is valid, None otherwise."""
    if not token or "." not in token:
        return None
    raw, _, sig = token.partition(".")
    try:
        payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(actual, expected):
            return None
        data = json.loads(payload)
    except Exception:
        return None

    if data.get("purpose") != "reset":
        return None
    if time.time() - data.get("t", 0) > TOKEN_MAX_AGE:
        return None
    return data.get("e")
