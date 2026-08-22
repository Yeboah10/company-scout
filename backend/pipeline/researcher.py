import time
from typing import Callable

from backend.models.schemas import (
    CompanyAnalysis,
    CompanyBrief,
    ResearchEvidence,
    Source,
    SourceQuality,
)
from backend.pipeline.analyst import CompanyAnalyst
from backend.pipeline.extractor import EvidenceExtractor
from backend.pipeline.resolver import CompanyResolver
from backend.pipeline.scorer import CompanyScorer
from backend.pipeline.searcher import CompanySearcher
from backend.services.cache import BriefCache
from backend.services.llm import LLMService
from backend.services.search import SearchService


class InsufficientEvidenceError(Exception):
    """Nothing usable was found, so there is no honest brief to write."""


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

    def _resume(self, query: str, report) -> CompanyBrief | None:
        """Finish a run whose research succeeded but whose scoring did not."""
        partial = self.cache.get_partial(query)
        if not partial:
            return None

        try:
            evidence = ResearchEvidence.model_validate(partial["evidence"])
            analysis = CompanyAnalysis.model_validate(partial["analysis"])
        except (KeyError, ValueError) as e:
            # A schema change since the checkpoint was written; redo it
            # properly rather than resuming from something half-understood.
            print(f"[cache] Discarding unusable checkpoint: {e}", flush=True)
            return None

        print(
            f"[cache] Resuming {evidence.company.name} from saved research "
            f"({len(evidence.claims)} claims); only scoring remains.",
            flush=True,
        )

        start = time.time()
        report(5, "Scoring opportunity...")
        analysis.scores = self.scorer.score(evidence, analysis)

        brief = CompanyBrief(
            evidence=evidence,
            analysis=analysis,
            duration_seconds=round(time.time() - start, 2),
        )
        self.cache.set(query, brief)
        return brief

    def research(
        self,
        query: str,
        use_cache: bool = True,
        progress: Callable[[int, str], None] | None = None,
    ) -> CompanyBrief:
        """Research a company end to end.

        `progress`, when given, is called as each stage begins so a caller
        polling from outside can report real progress rather than guessing
        from a timer.
        """
        start = time.time()

        def report(stage: int, message: str) -> None:
            print(f"[{stage}/5] {message}", flush=True)
            if progress is not None:
                progress(stage, message)

        if use_cache:
            cached = self.cache.get(query)
            if cached is not None:
                print(f"[cache] Serving cached brief for: {query}", flush=True)
                return cached

            # A previous run may have finished the research and died at
            # scoring. Resuming costs one call instead of six.
            resumed = self._resume(query, report)
            if resumed is not None:
                return resumed

        report(1, "Resolving company identity...")
        company, resolver_results = self.resolver.resolve(query)
        print(f"       > {company.name} ({company.country or 'unknown country'})", flush=True)

        report(2, "Searching for evidence...")
        search_results = self.searcher.search_company(company)
        all_results = resolver_results + search_results
        print(f"       > {len(all_results)} unique sources found", flush=True)

        report(3, "Extracting structured evidence...")
        claims, people = self.extractor.extract(company, all_results)
        print(f"       > {len(claims)} claims, {len(people)} people extracted", flush=True)

        # Analysis and scoring will happily produce confident-sounding prose
        # from nothing at all. If extraction came back empty, the honest
        # answer is that we found nothing — not a brief that looks researched.
        if not claims and not people:
            raise InsufficientEvidenceError(
                f"No usable evidence could be extracted for '{company.name}'. "
                "The company may be too small or too new to have a public record, "
                "or the name may need to be more specific."
            )

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

        report(4, "Analysing strategic signals and opportunities...")
        analysis = self.analyst.analyse(evidence)

        # Checkpoint before scoring: everything above this line is expensive
        # and already done, and scoring is the call most likely to hit the
        # daily ceiling because it goes last.
        if use_cache:
            self.cache.set_partial(
                query,
                {
                    "evidence": evidence.model_dump(mode="json"),
                    "analysis": analysis.model_dump(mode="json"),
                    "started": start,
                },
            )
        print(
            f"       > {len(analysis.signals)} signals, "
            f"{len(analysis.story_angles)} story angles",
            flush=True,
        )

        report(5, "Scoring opportunity...")
        scores = self.scorer.score(evidence, analysis)
        analysis.scores = scores
        print(
            f"       > Overall: {scores.overall_score}/10 ({scores.recommendation})",
            flush=True,
        )

        duration = time.time() - start
        brief = CompanyBrief(
            evidence=evidence,
            analysis=analysis,
            duration_seconds=round(duration, 2),
        )

        if use_cache:
            self.cache.set(query, brief)

        return brief
