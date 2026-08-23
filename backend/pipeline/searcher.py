from datetime import date

from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.search import SearchService
from backend.services.sources import AFRICAN_TECH_PRESS


# The things worth knowing about a company, each searched for deliberately.
#
# The previous queries were generic — "products services", "funding raised" —
# and left the specifics to whatever happened to rank. Pula's evidence came
# back with no mention of satellite data, which is central to what it sells,
# because nothing ever asked how the product works.
#
# Named areas rather than a flat list, so evidence coverage can be reported
# against them: knowing the technology question went unanswered is more useful
# than a confidence score on the answers that did come back.
COVERAGE_AREAS: list[tuple[str, str]] = [
    ("identity", "what the company does products services"),
    ("technology", "technology data platform how the product works"),
    ("business_model", "business model revenue pricing how it makes money"),
    ("capital", "funding raised investors valuation"),
    ("customers", "customers users clients who uses it"),
    ("geography", "markets countries operations expansion"),
    ("people", "founders CEO leadership executives"),
    ("recent", "news announcements {years}"),
    # Explicitly adversarial. Every other query is framed positively, so
    # trouble only surfaced when it happened to accompany good news — Twiga's
    # 300 job cuts arrived attached to a funding story.
    ("challenges", "challenges criticism losses layoffs shutdown problems"),
]


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
            (f"{name} {country} {template.format(years=recent_years)}", None)
            for _, template in COVERAGE_AREAS
        ] + [
            # Two passes restricted to outlets that actually report on these
            # markets. Left to open search these are outranked by syndicated
            # press releases, so they are asked for directly instead.
            (f"{name} {country}", AFRICAN_TECH_PRESS),
            (f"{name} funding launch expansion {recent_years}", AFRICAN_TECH_PRESS),
        ]

        return self.search.search_multiple(queries, max_results_per_query=5)
