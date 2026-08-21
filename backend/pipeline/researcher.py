import time

from backend.models.schemas import CompanyBrief, ResearchEvidence, Source, SourceQuality
from backend.pipeline.analyst import CompanyAnalyst
from backend.pipeline.extractor import EvidenceExtractor
from backend.pipeline.resolver import CompanyResolver
from backend.pipeline.scorer import CompanyScorer
from backend.pipeline.searcher import CompanySearcher
from backend.services.cache import BriefCache
from backend.services.llm import LLMService
from backend.services.search import SearchService


def _classify_source_quality(url: str, publisher: str | None) -> SourceQuality:
    url_lower = url.lower()
    pub_lower = (publisher or "").lower()

    tier_1_signals = [
        "gov.", ".gov", "sec.gov", "investor", "annual-report",
        "regulatory", "filing",
    ]
    tier_2_signals = [
        "reuters", "bloomberg", "techcrunch", "ft.com", "bbc",
        "cnbc", "forbes", "techpoint", "disrupt-africa", "techcabal",
        "ventureburn", "africanews", "theafricareport", "stears",
        "businessday", "guardian.ng", "nation.africa",
    ]

    combined = url_lower + " " + pub_lower

    if any(s in combined for s in tier_1_signals):
        return SourceQuality.TIER_1
    if any(s in combined for s in tier_2_signals):
        return SourceQuality.TIER_2
    return SourceQuality.TIER_3


class ResearchPipeline:
    def __init__(self):
        self.search = SearchService()
        self.llm = LLMService()
        self.resolver = CompanyResolver(self.search, self.llm)
        self.searcher = CompanySearcher(self.search)
        self.extractor = EvidenceExtractor(self.llm)
        self.analyst = CompanyAnalyst(self.llm)
        self.scorer = CompanyScorer(self.llm)
        self.cache = BriefCache()

    def research(self, query: str, use_cache: bool = True) -> CompanyBrief:
        start = time.time()

        if use_cache:
            cached = self.cache.get(query)
            if cached is not None:
                print(f"[cache] Serving cached brief for: {query}")
                return cached

        print(f"[1/5] Resolving company identity: {query}")
        company, resolver_results = self.resolver.resolve(query)
        print(f"       > {company.name} ({company.country or 'unknown country'})")

        print(f"[2/5] Searching for evidence...")
        search_results = self.searcher.search_company(company)
        all_results = resolver_results + search_results
        print(f"       > {len(all_results)} unique sources found")

        print(f"[3/5] Extracting structured evidence...")
        claims, people = self.extractor.extract(company, all_results)
        print(f"       > {len(claims)} claims, {len(people)} people extracted")

        sources = []
        seen = set()
        for r in all_results:
            if r.url not in seen:
                seen.add(r.url)
                quality = _classify_source_quality(r.url, None)
                sources.append(
                    Source(
                        url=r.url,
                        title=r.title,
                        published_date=r.published_date,
                        source_quality=quality,
                        snippet=r.snippet,
                    )
                )

        for claim in claims:
            claim.source.source_quality = _classify_source_quality(
                claim.source.url, claim.source.publisher
            )

        evidence = ResearchEvidence(
            company=company,
            claims=claims,
            people=people,
            sources=sources,
            raw_search_results=all_results,
        )

        print(f"[4/5] Analysing strategic signals and opportunities...")
        analysis = self.analyst.analyse(evidence)
        print(f"       > {len(analysis.signals)} signals, {len(analysis.story_angles)} story angles")

        print(f"[5/5] Scoring opportunity...")
        scores = self.scorer.score(evidence, analysis)
        analysis.scores = scores
        print(f"       > Overall: {scores.overall_score}/10 ({scores.recommendation})")

        duration = time.time() - start
        brief = CompanyBrief(
            evidence=evidence,
            analysis=analysis,
            duration_seconds=round(duration, 2),
        )

        if use_cache:
            self.cache.set(query, brief)

        return brief
