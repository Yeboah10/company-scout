from datetime import date

from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.coverage import COVERAGE_AREAS
from backend.services.search import SearchService
from backend.services.sources import AFRICAN_TECH_PRESS

# The areas themselves live in services/coverage.py, next to the code that
# reports on them: a question the search stops asking and a gap the brief stops
# reporting are the same edit, and splitting them across two files is how they
# drift apart.


class CompanySearcher:
    def __init__(self, search: SearchService):
        self.search = search

    def search_company(self, company: CompanyIdentity) -> list[SearchResult]:
        name = company.name
        country = company.country or ""
        # The industry is what disambiguates a name that collides. Searching
        # "Spiro United Arab Emirates technology platform" returned the App
        # Store listing for Spiro.AI, an unrelated CRM product — four of the
        # five results for that area were the wrong company entirely. Adding
        # "Electric vehicles" to the query is the difference between asking
        # about a company and asking about a word.
        industry = company.industry or ""

        # Derived from today rather than hardcoded, so the recency bias in
        # this query doesn't silently go stale as years pass.
        this_year = date.today().year
        recent_years = f"{this_year - 1} {this_year}"

        queries: list[tuple[str, list[str] | None]] = [
            (f"{name} {country} {industry} {template.format(years=recent_years)}", None)
            for _, _, template in COVERAGE_AREAS
        ] + [
            # Two passes restricted to outlets that actually report on these
            # markets. Left to open search these are outranked by syndicated
            # press releases, so they are asked for directly instead.
            (f"{name} {country}", AFRICAN_TECH_PRESS),
            (f"{name} funding launch expansion {recent_years}", AFRICAN_TECH_PRESS),
        ]

        # The African-press passes are broad by design and belong to no single
        # area, so they carry no label rather than a misleading one.
        areas = [key for key, _, _ in COVERAGE_AREAS] + ["", ""]

        return self.search.search_multiple(
            queries, max_results_per_query=5, areas=areas
        )
