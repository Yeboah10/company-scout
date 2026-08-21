from backend.models.schemas import (
    Claim,
    Confidence,
    CompanyIdentity,
    Person,
    SearchResult,
    Source,
    SourceQuality,
)
from backend.services.llm import LLMService, QuotaExhaustedError

SYSTEM_PROMPT = """You are an evidence extraction specialist for a company research tool focused on African companies and markets.

Given search results about a company, extract structured claims and people. You MUST distinguish facts from interpretation.

Return ONLY valid JSON in this exact format:
{
    "claims": [
        {
            "statement": "The factual claim exactly as supported by the source",
            "claim_type": "funding|expansion|product|leadership|partnership|customer|market|hiring|announcement|other",
            "source_url": "URL where this claim is supported",
            "source_title": "Title of the source page",
            "source_publisher": "Publisher name or null",
            "published_date": "YYYY-MM-DD or null",
            "confidence": "high|medium|low",
            "date_of_event": "YYYY-MM-DD or approximate date or null"
        }
    ],
    "people": [
        {
            "name": "Full Name",
            "role": "Their title/role",
            "relationship": "founder|executive|board_member|investor",
            "source_url": "URL confirming this",
            "source_title": "Source title",
            "confidence": "high|medium|low"
        }
    ]
}

Rules:
- ONLY extract claims directly supported by the search results provided
- Do NOT infer, speculate, or add information not in the sources
- Distinguish between "raised $X" vs "announced plans to raise $X"
- Distinguish between confirmed facts and reported/alleged facts
- If a claim appears in multiple sources, use the most authoritative one
- Set confidence to "high" only when the source is authoritative and the claim is specific
- Set confidence to "low" for claims from secondary/aggregator sources without corroboration
- For people, only include those with clear evidence of their role
- Prefer recent information over outdated information
"""


class EvidenceExtractor:
    def __init__(self, llm: LLMService):
        self.llm = llm

    def extract(
        self, company: CompanyIdentity, search_results: list[SearchResult]
    ) -> tuple[list[Claim], list[Person]]:
        if not search_results:
            return [], []

        batches = [
            search_results[i : i + 10] for i in range(0, len(search_results), 10)
        ]

        # Deliberately sequential. These batches are independent and running
        # them concurrently is tempting, but the Gemini free tier's
        # requests-per-minute cap is the binding constraint: a parallel burst
        # exhausts the minute's budget and the later analyst/scorer stages
        # then stall in rate-limit backoff, making the whole run slower.
        # Measured: 317s parallel vs ~255s sequential.
        chunks = []
        for batch in batches:
            try:
                chunks.append(self._extract_chunk(company, batch))
            except QuotaExhaustedError:
                # Every remaining batch would fail the same way, and a brief
                # built on partial evidence reads exactly as confident as one
                # built on all of it. Abort rather than quietly under-report.
                raise
            except Exception as e:
                # Losing one batch costs some evidence but shouldn't fail the run.
                print(f"       ! Extraction failed for a batch: {e}", flush=True)
                chunks.append(([], []))

        all_claims = []
        all_people = []
        seen_claims = set()
        seen_people = set()

        for claims, people in chunks:
            for claim in claims:
                key = claim.statement.lower().strip()
                if key not in seen_claims:
                    seen_claims.add(key)
                    all_claims.append(claim)
            for person in people:
                key = person.name.lower().strip()
                if key not in seen_people:
                    seen_people.add(key)
                    all_people.append(person)

        return all_claims, all_people

    def _extract_chunk(
        self, company: CompanyIdentity, results: list[SearchResult]
    ) -> tuple[list[Claim], list[Person]]:
        snippets = "\n\n".join(
            f"[Source {i+1}]\nTitle: {r.title}\nURL: {r.url}\nDate: {r.published_date or 'unknown'}\nContent: {r.snippet}"
            for i, r in enumerate(results)
        )

        user_prompt = (
            f"Company: {company.name}\n"
            f"Country: {company.country or 'Unknown'}\n"
            f"Industry: {company.industry or 'Unknown'}\n\n"
            f"Search results:\n{snippets}"
        )

        data = self.llm.extract_structured(SYSTEM_PROMPT, user_prompt)

        claims = []
        for c in data.get("claims", []):
            source = Source(
                url=c.get("source_url", ""),
                title=c.get("source_title", ""),
                publisher=c.get("source_publisher"),
                published_date=c.get("published_date"),
            )
            claims.append(
                Claim(
                    statement=c["statement"],
                    claim_type=c.get("claim_type", "other"),
                    source=source,
                    confidence=Confidence(c.get("confidence", "medium")),
                    date_of_event=c.get("date_of_event"),
                )
            )

        people = []
        for p in data.get("people", []):
            source = Source(
                url=p.get("source_url", ""),
                title=p.get("source_title", ""),
            )
            people.append(
                Person(
                    name=p["name"],
                    role=p.get("role", "Unknown"),
                    relationship=p.get("relationship", "executive"),
                    source=source,
                    confidence=Confidence(p.get("confidence", "medium")),
                )
            )

        return claims, people
