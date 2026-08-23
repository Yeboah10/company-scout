"""Measuring what the research did not find out.

A brief reports what it found. It has never reported what it went looking for
and came back empty-handed on, which is the more useful half when you are
deciding whether to trust it: "no claim about how they make money" is a fact
about the company's public record, and it reads very differently from silence.

Coverage is measured structurally, not semantically. Each search is tagged with
the area it was asked on behalf of, and an area counts as covered when a page
that search surfaced went on to produce a claim the extractor kept. That is a
weaker statement than "the technology question was answered" — it is "the
technology search found something worth extracting" — but it is true, it costs
nothing, and it cannot drift the way a keyword list would.
"""

from backend.models.schemas import AreaCoverage, CoverageReport, ResearchEvidence

# The things worth knowing about a company, each searched for deliberately.
#
# The queries were once generic — "products services", "funding raised" — and
# left the specifics to whatever happened to rank. Pula's evidence came back
# with no mention of satellite data, which is central to what it sells, because
# nothing ever asked how the product works.
#
# (key, what to call it in a report, query template)
COVERAGE_AREAS: list[tuple[str, str, str]] = [
    ("identity", "What they do", "what the company does products services"),
    ("technology", "How the product works",
     "technology data platform how the product works"),
    ("business_model", "How they make money",
     "business model revenue pricing how it makes money"),
    ("capital", "Funding and investors", "funding raised investors valuation"),
    ("customers", "Who uses it", "customers users clients who uses it"),
    ("geography", "Where they operate", "markets countries operations expansion"),
    ("people", "Who runs it", "founders CEO leadership executives"),
    ("recent", "What happened lately", "news announcements {years}"),
    # Explicitly adversarial. Every other query is framed positively, so
    # trouble only surfaced when it happened to accompany good news — Twiga's
    # 300 job cuts arrived attached to a funding story.
    ("challenges", "What is going wrong",
     "challenges criticism losses layoffs shutdown problems"),
]

_LABELS = {key: label for key, label, _ in COVERAGE_AREAS}


def measure(evidence: ResearchEvidence) -> CoverageReport:
    """Which coverage areas produced evidence, and which came back empty."""
    # A URL can be surfaced by several areas, and each of them deserves the
    # credit: the challenges search finding the same page as the capital
    # search is not a failure of the challenges search.
    urls_by_area: dict[str, set[str]] = {key: set() for key, _, _ in COVERAGE_AREAS}
    for result in evidence.raw_search_results:
        for area in result.areas:
            if area in urls_by_area:
                urls_by_area[area].add(result.url)

    claim_urls = [claim.source.url for claim in evidence.claims]

    areas = []
    for key, label, _ in COVERAGE_AREAS:
        urls = urls_by_area[key]
        claims = sum(1 for url in claim_urls if url in urls)
        areas.append(
            AreaCoverage(
                area=key,
                label=label,
                results=len(urls),
                claims=claims,
                covered=claims > 0,
            )
        )

    return CoverageReport(areas=areas)


def label_for(area: str) -> str:
    return _LABELS.get(area, area)
