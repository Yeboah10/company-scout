"""Optional email lookup via Hunter.io.

Contact databases (RocketReach, ContactOut, Apollo and the rest) hold exactly
the data this feature wants, but scraping them is not an option: they sit
behind logins and bot detection, their terms forbid it, and the records are
personal data whose handling carries real obligations under GDPR and under
Nigeria's NDPA, Kenya's DPA and Ghana's DPA. Building that into a public site
would put the liability on its owner.

The same data is available through the front door. Hunter.io publishes an API
that returns a domain's known addresses and its address format, which is
precisely the two things this feature needs. The free tier allows 25 searches
a month, and nothing here runs unless a key is configured.
"""

import threading
import time

import httpx

from backend.config import settings
from backend.services.usage import usage

BASE = "https://api.hunter.io/v2"
TIMEOUT = 12.0

# The account endpoint is free and does not consume a search, but it is still
# a network call and the usage page can be refreshed repeatedly.
_ACCOUNT_TTL = 300.0
_account_lock = threading.Lock()
_account_cache: tuple[float, dict] | None = None

# What happened the last time a lookup was actually attempted. Our own counter
# says Hunter was called three times; Hunter's account says zero searches were
# used. Both cannot be right, and with no record of the outcome there is no
# way to tell a failing call from a stale counter.
_last_lookup: dict | None = None


def last_lookup() -> dict | None:
    return _last_lookup


def is_configured() -> bool:
    return bool(settings.hunter_api_key)


def account(force: bool = False) -> dict:
    """Whether the key actually works, and what Hunter itself says is left.

    `is_configured()` only reports that an environment variable exists. A
    rejected key looks exactly like a working one until the first lookup, which
    is the shape of failure this project has been bitten by before — so ask.

    Hunter's own remaining count is also better than ours: it counts every
    search on the account, including ones this process never saw.
    """
    global _account_cache

    if not is_configured():
        return {"configured": False, "valid": None, "reason": "no key set"}

    with _account_lock:
        if not force and _account_cache and time.time() - _account_cache[0] < _ACCOUNT_TTL:
            return _account_cache[1]

    try:
        r = httpx.get(
            f"{BASE}/account",
            params={"api_key": settings.hunter_api_key},
            timeout=TIMEOUT,
        )
        if r.status_code in (401, 403):
            out = {"configured": True, "valid": False, "reason": "key rejected"}
        else:
            r.raise_for_status()
            data = r.json().get("data") or {}
            searches = ((data.get("requests") or {}).get("searches") or {})
            out = {
                "configured": True,
                "valid": True,
                "plan": data.get("plan_name"),
                "used": searches.get("used"),
                "limit": searches.get("available"),
            }
    except Exception as e:
        # Unknown rather than invalid: a timeout says nothing about the key.
        out = {"configured": True, "valid": None, "reason": f"check failed: {e}"}

    with _account_lock:
        _account_cache = (time.time(), out)
    return out


def remaining() -> int | None:
    """Lookups left according to Hunter, or None if it could not be asked.

    Preferred over any count kept here. The free allowance was assumed to be
    25 and Hunter reported 50 the first time it was actually asked, which is
    the general argument against hardcoding another service's limits.
    """
    a = account()
    if a.get("valid") and a.get("limit") is not None and a.get("used") is not None:
        return max(0, a["limit"] - a["used"])
    return None


def domain_search(domain: str, limit: int = 10) -> dict | None:
    """Addresses Hunter holds for a domain, plus the format it has inferred.

    Returns None on any failure: this is an enrichment, and a brief without it
    is still a brief.
    """
    if not is_configured() or not domain:
        return None

    global _last_lookup
    import time as _time

    def note(outcome: str, **extra) -> None:
        global _last_lookup
        _last_lookup = {"at": _time.time(), "domain": domain,
                        "outcome": outcome, **extra}

    try:
        usage.record_hunter()
        r = httpx.get(
            f"{BASE}/domain-search",
            params={
                "domain": domain,
                "api_key": settings.hunter_api_key,
                "limit": limit,
            },
            timeout=TIMEOUT,
        )
        if r.status_code == 401:
            print("       ! Hunter key rejected", flush=True)
            note("key_rejected", status=401)
            return None
        if r.status_code == 429:
            print("       ! Hunter monthly allowance used up", flush=True)
            note("rate_limited", status=429)
            return None
        if r.status_code >= 400:
            # Anything else — a plan restriction, a bad parameter — used to
            # vanish into a generic exception message nobody ever read.
            body = (r.text or "")[:200]
            print(f"       ! Hunter returned {r.status_code}: {body}", flush=True)
            note("http_error", status=r.status_code, detail=body)
            return None
        data = r.json().get("data")
        found = len((data or {}).get("emails") or [])
        print(f"       > Hunter returned {found} address(es) for {domain}",
              flush=True)
        note("ok", status=r.status_code, emails=found)
        return data
    except Exception as e:
        print(f"       ! Hunter lookup failed: {e}", flush=True)
        note("exception", detail=f"{type(e).__name__}: {e}"[:200])
        return None


def parse_domain_search(data: dict | None) -> tuple[list[dict], str | None]:
    """Normalise Hunter's response into (emails, pattern).

    Hunter's own confidence score is carried through rather than reinterpreted:
    it knows how it verified an address and this code does not.
    """
    if not data:
        return [], None

    pattern = data.get("pattern")  # e.g. "{first}.{last}"
    emails = []
    for e in data.get("emails", []) or []:
        value = e.get("value")
        if not value:
            continue
        name = " ".join(
            part for part in (e.get("first_name"), e.get("last_name")) if part
        )
        emails.append(
            {
                "email": value,
                "person": name or None,
                "role": e.get("position"),
                "kind": "role" if e.get("type") == "generic" else "personal",
                "confidence": e.get("confidence"),
                "source_url": (e.get("sources") or [{}])[0].get("uri"),
            }
        )
    return emails, pattern
