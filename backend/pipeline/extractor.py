from backend.models.schemas import (
    Claim,
    Confidence,
    CompanyIdentity,
    Person,
    SearchResult,
    Source,
    SourceQuality,
)
from backend.services import monitoring
from backend.services.llm import LLMService, QuotaExhaustedError
from backend.models.schemas import RoleStatus


def _role_status(raw) -> RoleStatus:
    """Anything unrecognised becomes "unclear" rather than "current".

    The safe failure here is under-claiming. An outreach email to a person
    who left is a worse outcome than a brief that declines to promise they
    are still there.
    """
    try:
        return RoleStatus(str(raw).strip().lower())
    except (ValueError, AttributeError):
        return RoleStatus.UNCLEAR

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
            "status": "current|former|unclear",
            "role_start": "YYYY-MM or YYYY or null",
            "role_end": "YYYY-MM or YYYY or null",
            "as_of": "YYYY-MM-DD the source was published, or null",
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

People and time — read this carefully:
- Do NOT ask "is this person currently the CEO?". Ask "what does this source
  establish about their role, and as of when?"
- "status" is what the SOURCE supports, not what you believe to be true today:
    "current" only when the source states or clearly implies they hold the role
      at the time it was written, AND the source is recent
    "former" when the source says they left, stepped down, were replaced, or
      describes the role in the past tense
    "unclear" when the source names their role but gives no timeframe, or the
      source is old enough that the role may since have changed
- A person quoted in an article ("...said X, chief executive") establishes the
  role as of that article's publication date. That is "unclear" unless the
  article is recent, never automatically "current".
- If a newer source names a different holder of the same role, mark the older
  holder "former".
- "as_of" is the source's publication date. Leave it null rather than guessing.
- Prefer recent information over outdated information, and when two sources
  disagree about who holds a role, prefer the more recent one and mark the
  other "former".
"""


def _is_partial_name(name: str, seen: set[str]) -> bool:
    """Whether `name` is a fragment of a fuller name already collected."""
    parts = name.split()
    if len(parts) > 1:
        return False
    return any(name in other.split() for other in seen if len(other.split()) > 1)


def _drop_partial_names(people: list[Person]) -> list[Person]:
    """Remove single-word entries that are part of a fuller name in the list."""
    full = {
        part
        for p in people
        for part in p.name.lower().split()
        if len(p.name.split()) > 1
    }
    return [
        p for p in people
        if len(p.name.split()) > 1 or p.name.lower() not in full
    ]


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
                # The brief still renders, just with less in it. Nothing on
                # screen says so, which is why this is worth reporting.
                monitoring.capture(e, stage="extraction", company=company.name)
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
                if key in seen_people:
                    continue
                # One batch says "Anant Badjatya", another says "Badjatya",
                # and the brief listed both as separate executives — then
                # offered each of them an inferred email address. A bare
                # surname that already appears inside a fuller name is the
                # same person, and the fuller name is the one worth keeping.
                if _is_partial_name(key, seen_people):
                    continue
                seen_people.add(key)
                all_people.append(person)

        # A fuller name can also arrive after the short one. Drop the short
        # entry rather than leave the duplicate that arrived first.
        all_people = _drop_partial_names(all_people)

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
            statement = c.get("statement")
            if not statement:
                # The model occasionally drops this field on one entry inside
                # an otherwise-good batch. That used to raise a KeyError which
                # discarded the whole batch's claims AND people (the enclosing
                # try/except in extract() catches it, but only after every
                # good entry already parsed is thrown away with the bad one).
                # Skip just this claim instead.
                monitoring.warn(
                    "extraction: claim missing 'statement', skipped",
                    company=company.name,
                )
                continue
            source = Source(
                url=c.get("source_url", ""),
                title=c.get("source_title", ""),
                publisher=c.get("source_publisher"),
                published_date=c.get("published_date"),
            )
            claims.append(
                Claim(
                    statement=statement,
                    claim_type=c.get("claim_type", "other"),
                    source=source,
                    confidence=Confidence(c.get("confidence", "medium")),
                    date_of_event=c.get("date_of_event"),
                )
            )

        people = []
        for p in data.get("people", []):
            name = p.get("name")
            if not name:
                # Same reasoning as above: skip this one entry, keep the rest.
                monitoring.warn(
                    "extraction: person missing 'name', skipped",
                    company=company.name,
                )
                continue
            source = Source(
                url=p.get("source_url", ""),
                title=p.get("source_title", ""),
                published_date=p.get("as_of"),
            )
            people.append(
                Person(
                    name=name,
                    role=p.get("role", "Unknown"),
                    relationship=p.get("relationship", "executive"),
                    source=source,
                    confidence=Confidence(p.get("confidence", "medium")),
                    # Defaults to unclear, not current. An unlabelled role is
                    # an undated one, and the whole point of these fields is
                    # that undated must not read as current.
                    status=_role_status(p.get("status")),
                    role_start=p.get("role_start"),
                    role_end=p.get("role_end"),
                    as_of=p.get("as_of"),
                )
            )

        return claims, people
