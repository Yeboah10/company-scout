from datetime import date

from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.search import SearchService


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

        queries = [
            f"{name} {country} company overview products services",
            f"{name} {country} funding raised investment investors",
            f"{name} {country} recent news announcements {recent_years}",
            f"{name} founders CEO leadership team executives",
            f"{name} {country} expansion partnerships customers",
        ]

        return self.search.search_multiple(queries, max_results_per_query=5)
