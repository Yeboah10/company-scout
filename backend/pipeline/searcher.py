from datetime import date

from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.search import SearchService
from backend.services.sources import AFRICAN_TECH_PRESS


class CompanySearcher:
    def __init__(self, search: SearchService):
        self.search = search

    def search_company(self, company: CompanyIdentity) -> list[SearchResult]:
        name = company.name
        country = company.country or ""

        # Derived from today rather than hardcoded, so the recency bias in
        # this query doesn't silently go stale as years pass.
        this_year = date.today().year
        recent_years = f"{this_year - 1} {this_year}"

        queries: list[tuple[str, list[str] | None]] = [
            (f"{name} {country} company overview products services", None),
            (f"{name} {country} funding raised investment investors", None),
            (f"{name} {country} recent news announcements {recent_years}", None),
            (f"{name} founders CEO leadership team executives", None),
            (f"{name} {country} expansion partnerships customers", None),
            # Two passes restricted to outlets that actually report on these
            # markets. Left to open search these are outranked by syndicated
            # press releases, so they are asked for directly instead.
            (f"{name} {country}", AFRICAN_TECH_PRESS),
            (f"{name} funding launch expansion {recent_years}", AFRICAN_TECH_PRESS),
        ]

        return self.search.search_multiple(queries, max_results_per_query=5)
