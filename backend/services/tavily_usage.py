"""What Tavily itself says we have spent.

Our own counter was wrong by more than 800 searches: it reported 367 used
while Tavily reported 1,205 against a 1,000 limit. It only ever counted calls
this process observed, and it was added long after the account started being
used, so everything before that was invisible to it.

This is the third time the same lesson has come up here — Redis that parsed
but never connected, a Hunter key that was set but never called, and now a
search counter confidently reporting headroom that did not exist. A number we
derive ourselves is a guess. The provider's own number is the fact.
"""

import threading
import time

import httpx

from backend.config import settings

_URL = "https://api.tavily.com/usage"
_TTL = 300.0
_lock = threading.Lock()
_cached: tuple[float, dict] | None = None


def fetch(force: bool = False) -> dict:
    """Tavily's own account usage, or a dict explaining why it is unknown."""
    global _cached
    if not settings.tavily_api_key:
        return {"available": False, "reason": "no key set"}

    with _lock:
        if not force and _cached and time.time() - _cached[0] < _TTL:
            return _cached[1]

    try:
        r = httpx.get(
            _URL,
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            timeout=10.0,
        )
        r.raise_for_status()
        account = (r.json() or {}).get("account") or {}
        used = account.get("plan_usage")
        limit = account.get("plan_limit")
        out = {
            "available": True,
            "plan": account.get("current_plan"),
            "used": used,
            "limit": limit,
            "remaining": (max(0, limit - used)
                          if isinstance(used, int) and isinstance(limit, int)
                          else None),
            "exhausted": (isinstance(used, int) and isinstance(limit, int)
                          and used >= limit),
        }
    except Exception as e:
        out = {"available": False, "reason": f"{type(e).__name__}: {e}"[:200]}

    with _lock:
        _cached = (time.time(), out)
    return out


def is_exhausted() -> bool:
    """Whether Tavily says the plan is spent.

    False when unknown: a failed check must not stop the pipeline from trying,
    since the search itself is the more reliable test of whether it works.
    """
    return bool(fetch().get("exhausted"))
