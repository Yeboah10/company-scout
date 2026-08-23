"""The Postgres connection, and an honest answer about whether it works.

Until now everything durable lived in a Redis cache with a seven-day expiry.
That is fine for "serve this report again quickly" and wrong for everything
the product is growing into: a watchlist, a history of what changed between
scouts, an evaluation record, accounts. Those need rows that outlive a cache.

This module deliberately does the smallest useful thing first — connect, and
report truthfully whether the connection works. A database that is configured
but unreachable looks exactly like one that is fine until the first write
fails, and that is the failure this project has been bitten by twice (Redis
that parsed but never connected; a Hunter key that was set but never called).
"""

import threading
import time

from backend.config import settings

# Reported by /health. Refreshed rather than cached forever: a database that
# was reachable at start-up is not necessarily reachable now.
_CHECK_TTL = 60.0
_lock = threading.Lock()
_cached: tuple[float, dict] | None = None


def is_configured() -> bool:
    return bool(settings.database_url)


def connect():
    """A raw connection, for modules that need more than a health check.

    Kept in one place so store.py, users.py and this module's own probe agree
    on how to reach Postgres, rather than each carrying a slightly different
    copy of the same six lines.
    """
    import psycopg
    return psycopg.connect(settings.database_url, connect_timeout=10)


def _probe() -> dict:
    if not is_configured():
        return {"configured": False, "connected": None, "reason": "no DATABASE_URL set"}

    try:
        import psycopg
    except ImportError:
        return {"configured": True, "connected": None,
                "reason": "psycopg not installed"}

    try:
        started = time.time()
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = (cur.fetchone() or [""])[0]
        return {
            "configured": True,
            "connected": True,
            # Neon sleeps after five minutes idle and wakes on connect, so the
            # first call after a quiet spell is slow by design, not broken.
            "latency_ms": int((time.time() - started) * 1000),
            "server": version.split(" on ")[0] if version else None,
        }
    except Exception as e:
        return {"configured": True, "connected": False,
                "reason": f"{type(e).__name__}: {e}"[:200]}


def status(force: bool = False) -> dict:
    global _cached
    with _lock:
        if not force and _cached and time.time() - _cached[0] < _CHECK_TTL:
            return _cached[1]
    result = _probe()
    with _lock:
        _cached = (time.time(), result)
    return result
