from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.search import SearchService


class CompanySearcher:
    def __init__(self, search: SearchService):
        self.search = search

    def search_company(self, company: CompanyIdentity) -> list[SearchResult]:
        name = company.name
        country = company.country or ""

        queries = [
            f"{name} {country} company overview products services",
            f"{name} {country} funding raised investment investors",
            f"{name} {country} recent news announcements 2025 2026",
            f"{name} founders CEO leadership team executives",
            f"{name} {country} expansion partnerships customers",
        ]

        return self.search.search_multiple(queries, max_results_per_query=5)
