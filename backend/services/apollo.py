"""Optional email lookup via Apollo.io.

An alternative to Hunter, not a replacement: they answer different questions.
Hunter is domain-first ("what addresses exist at acme.com, and what format do
they follow?"). Apollo is person-first ("what is this named person's address?").
Given the pipeline already knows who the executives are, person-first is the
better fit, and Apollo's free allowance is the larger of the two.

Apollo's free plan can call People Enrichment, but only from an account
registered with a work email address — a personal Gmail is refused.

Costs one credit per email revealed, and only when something is found. Nothing
here runs unless a key is configured.
"""

import httpx

from backend.config import settings
from backend.services.usage import usage

BASE = "https://api.apollo.io/api/v1"
TIMEOUT = 15.0


def is_configured() -> bool:
    return bool(settings.apollo_api_key)


def find_person_email(
    first_name: str, last_name: str, domain: str
) -> dict | None:
    """Look up one named person at one company domain.

    Returns None on any failure, and on the "found nothing" case: this is an
    enrichment, and a brief without it is still a brief.
    """
    if not is_configured() or not domain or not (first_name and last_name):
        return None

    try:
        usage.record_apollo()
        r = httpx.post(
            f"{BASE}/people/match",
            headers={
                "x-api-key": settings.apollo_api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            json={
                "first_name": first_name,
                "last_name": last_name,
                "domain": domain,
                # Without this Apollo returns a masked placeholder rather than
                # the address. It is what costs the credit.
                "reveal_personal_emails": True,
            },
            timeout=TIMEOUT,
        )
        if r.status_code in (401, 403):
            print(
                "       ! Apollo rejected the key. Free-plan API access needs an "
                "account registered with a work email address.",
                flush=True,
            )
            return None
        if r.status_code == 422:
            # Apollo returns 422 for "no match", which is an answer, not a fault.
            return None
        if r.status_code == 429:
            print("       ! Apollo credits or rate limit exhausted", flush=True)
            return None
        r.raise_for_status()
        return r.json().get("person")
    except Exception as e:
        print(f"       ! Apollo lookup failed: {e}", flush=True)
        return None


def parse_person(person: dict | None) -> dict | None:
    """Normalise Apollo's person into the shape the prospector uses.

    Apollo returns a placeholder like "email_not_unlocked@domain.com" when it
    holds an address but has not revealed it. That is not an address, and
    passing it through would put a fake one in front of the user.
    """
    if not person:
        return None

    email = (person.get("email") or "").strip().lower()
    if not email or "email_not_unlocked" in email or "not_unlocked" in email:
        return None

    name = " ".join(
        p for p in (person.get("first_name"), person.get("last_name")) if p
    ).strip()

    return {
        "email": email,
        "person": name or None,
        "role": person.get("title"),
        "kind": "personal",
        "source_url": person.get("linkedin_url"),
    }
