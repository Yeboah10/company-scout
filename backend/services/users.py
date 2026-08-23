"""Real accounts, on top of the single-admin login that came first.

The site started with one operator and a password in the environment — the
same trust model as the admin token already in production. That stays valid
and keeps working: it is the way in if the database is ever unreachable.

This adds a second, additive way in: a `users` table, so more than one person
can have their own email and password. Nothing here removes the env-based
login; `auth.authenticate()` checks both and either can satisfy it.

Passwords are hashed with PBKDF2-SHA256, salted per user, 200,000 rounds. Not
bcrypt or argon2 — neither is already a dependency, and this is a research
tool's login, not a bank's. Constant-time comparison either way.
"""

import hashlib
import hmac
import os
import re

from backend.services.db import connect

_ITERATIONS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ready = False


def ensure_schema() -> bool:
    global _ready
    if _ready:
        return True
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
            conn.commit()
        _ready = True
        return True
    except Exception as e:
        print(f"[users] Could not prepare schema: {e}", flush=True)
        return False


def _hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return salt.hex() + "$" + digest.hex()


def _matches(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(actual, expected)


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def create(email: str, password: str) -> tuple[bool, str]:
    """Register one account. Returns (ok, message).

    Rejects on the way in rather than leaving a bad row for the login path to
    puzzle over later: no database, a malformed address, a password too short
    to be worth hashing, or an address already taken.
    """
    email = normalise_email(email)
    if not valid_email(email):
        return False, "Enter a valid email address."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not ensure_schema():
        return False, "Accounts are not available right now — the database is unreachable."

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
                if cur.fetchone():
                    return False, "An account with that email already exists."
                cur.execute(
                    "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                    (email, _hash(password)),
                )
            conn.commit()
        return True, "ok"
    except Exception as e:
        print(f"[users] Create failed: {e}", flush=True)
        return False, "Could not create the account. Please try again."


def verify(email: str, password: str) -> bool:
    """Whether this email/password pair matches a stored account."""
    email = normalise_email(email)
    if not email or not password or not ensure_schema():
        return False
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s", (email,)
                )
                row = cur.fetchone()
        if not row:
            return False
        return _matches(password, row[0])
    except Exception as e:
        print(f"[users] Verify failed: {e}", flush=True)
        return False
