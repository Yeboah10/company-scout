"""Exa — the search provider used when Tavily's monthly plan is spent.

Chosen over the alternatives for one reason that matters more than its free
allowance: it supports includeDomains and excludeDomains natively. Those are
not conveniences here. include_domains is what forces results from African
tech press instead of whatever ranks; exclude_domains is what keeps press
release wires and scraper directories out at the source. Brave, Serper and
SerpAPI have neither, and emulating them with site: operators inside the query
string breaks past a dozen domains — which would quietly undo the source
quality work rather than fail loudly.

Returns SearchResult objects, the same type Tavily's path produces, so
everything downstream is unaware of which provider answered.
"""

import httpx

from backend.config import settings
from backend.models.schemas import SearchResult
from backend.services.sources import clean_snippet

_URL = "https://api.exa.ai/search"
_TIMEOUT = 30.0


def is_configured() -> bool:
    return bool(settings.exa_api_key)


def search(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[SearchResult]:
    payload: dict = {
        "query": query,
        "numResults": max_results,
        # Ask for page text: the pipeline extracts claims from body text, so a
        # provider returning only links and titles would be useless to it.
        "contents": {"text": {"maxCharacters": 3000}},
    }
    if include_domains:
        payload["includeDomains"] = include_domains
    if exclude_domains:
        payload["excludeDomains"] = exclude_domains

    r = httpx.post(
        _URL,
        headers={
            "x-api-key": settings.exa_api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_TIMEOUT,
    )
    r.raise_for_status()

    results = []
    for item in (r.json() or {}).get("results", []):
        results.append(
            SearchResult(
                query=query,
                url=item.get("url", ""),
                title=item.get("title") or "",
                # Cleaned on the way in, exactly as Tavily's results are, so a
                # scraped navigation menu does not reach the extractor just
                # because it arrived by a different route.
                snippet=clean_snippet(item.get("text") or ""),
                published_date=item.get("publishedDate"),
                score=item.get("score"),
            )
        )
    return results
