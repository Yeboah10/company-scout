from backend.models.schemas import CompanyAnalysis, OpportunityScores, ResearchEvidence
from backend.services.llm import LLMService
from backend.services.recency import RecencyProfile, build_profile, recency_factor

# Statuses in which there is nobody left to contact.
DEFUNCT_STATUSES = {"defunct", "winding_down"}


def build_evidence_profile(evidence: ResearchEvidence) -> RecencyProfile:
    """Collect every date the evidence offers into one recency picture.

    A claim's date_of_event is preferred over its source's publication date:
    an article written last week about a 2019 funding round is old news, and
    the publication date would disguise that.
    """
    dates: list[str | None] = []

    for claim in evidence.claims:
        dates.append(claim.date_of_event or claim.source.published_date)

    # Sources with no claim attached still say something about how much recent
    # material exists about the company at all.
    claim_urls = {c.source.url for c in evidence.claims}
    for source in evidence.sources:
        if source.url not in claim_urls:
            dates.append(source.published_date)

    return build_profile(dates)

SCORER_SYSTEM_PROMPT = """You are a company opportunity scorer for a research tool focused on African companies.

Given company evidence and strategic analysis, score the company on four dimensions (0-10 each).

Return ONLY valid JSON in this exact format:
{
    "story_score": 7.5,
    "story_reasoning": "One sentence explaining the score",
    "case_study_score": 8.0,
    "case_study_reasoning": "One sentence explaining the score",
    "outreach_score": 6.0,
    "outreach_reasoning": "One sentence explaining the score",
    "research_score": 7.0,
    "research_reasoning": "One sentence explaining the score"
}

Scoring criteria:

STORY POTENTIAL (0-10):
- Novelty of the business model or approach
- Recent developments worth writing about
- Market relevance and timing
- Strategic tension or interesting dynamics
- Availability of data and sources

CASE STUDY POTENTIAL (0-10):
- Clear strategic decision that can be analyzed
- Tension or trade-off students/managers can debate
- Identifiable protagonist (decision maker)
- Observable business consequences
- Accessible information to write the case
- Possibility of getting primary interviews

OUTREACH POTENTIAL (0-10):
- Recent trigger event making contact timely
- Identifiable relevant decision maker
- Clear value proposition for the contact
- Accessible contact path
- Meaningful development to discuss

RESEARCH POTENTIAL (0-10):
- Information availability and quality
- Unresolved strategic questions worth investigating
- Market significance
- Data availability for quantitative analysis
- Strategic complexity worth deeper study

Rules:
- Be honest. Not every company is interesting. A boring company should score 3-4.
- A company with contradictory or sparse information should score lower.
- Weight recent developments more heavily.
- Consider the African market context specifically.
- Each score must have a specific, non-generic reasoning tied to actual evidence.
- Do NOT default to scores of 7-8. Use the full 0-10 range.
"""


class CompanyScorer:
    def __init__(self, llm: LLMService):
        self.llm = llm

    def score(self, evidence: ResearchEvidence, analysis: CompanyAnalysis) -> OpportunityScores:
        profile = build_evidence_profile(evidence)
        factor, note = recency_factor(profile)

        prompt = self._build_scoring_prompt(evidence, analysis, profile)
        data = self.llm.extract_structured(SCORER_SYSTEM_PROMPT, prompt)

        outreach_score = float(data["outreach_score"])
        outreach_reasoning = data["outreach_reasoning"]

        # A company that has shut down can still be a fine story, case study or
        # research subject — those dimensions legitimately stay high. But there
        # is nobody left to email, so outreach is not a matter of judgement.
        # Enforced here rather than left to the prompt: the model rated a
        # collapsed company 6.5 for outreach on the strength of how interesting
        # its collapse was.
        if analysis.operational_status in DEFUNCT_STATUSES:
            capped = min(outreach_score, 0.5)
            if capped < outreach_score:
                outreach_reasoning = (
                    f"No outreach is possible: the company is "
                    f"{analysis.operational_status.replace('_', ' ')}. "
                    + (analysis.status_evidence or "")
                ).strip()
            outreach_score = capped

        return OpportunityScores(
            story_score=float(data["story_score"]),
            story_reasoning=data["story_reasoning"],
            case_study_score=float(data["case_study_score"]),
            case_study_reasoning=data["case_study_reasoning"],
            outreach_score=outreach_score,
            outreach_reasoning=outreach_reasoning,
            research_score=float(data["research_score"]),
            research_reasoning=data["research_reasoning"],
            recency_factor=factor,
            recency_note=note,
        )

    def _build_scoring_prompt(
        self,
        evidence: ResearchEvidence,
        analysis: CompanyAnalysis,
        profile: RecencyProfile,
    ) -> str:
        c = evidence.company
        parts = [
            f"Company: {c.name} ({c.country or 'Unknown'})",
            f"Operational status: {analysis.operational_status}",
            f"Industry: {c.industry or 'Unknown'}",
            f"Founded: {c.founded_year or 'Unknown'}",
            f"Description: {c.description or 'Unknown'}",
            f"",
            f"Number of claims found: {len(evidence.claims)}",
            f"Number of people identified: {len(evidence.people)}",
            f"Number of sources: {len(evidence.sources)}",
            f"",
            f"EXECUTIVE SUMMARY:",
            analysis.executive_summary,
            f"",
            f"STRATEGIC SIGNALS ({len(analysis.signals)}):",
        ]

        for s in analysis.signals:
            parts.append(f"- {s.title}: {s.evidence}")

        parts.append(f"")
        parts.append(f"STORY ANGLES ({len(analysis.story_angles)}):")
        for a in analysis.story_angles:
            parts.append(f"- {a.angle}")

        if analysis.case_study:
            parts.append(f"")
            parts.append(f"CASE STUDY: {analysis.case_study.potential_title}")
            parts.append(f"Tension: {analysis.case_study.strategic_tension}")

        if analysis.outreach:
            parts.append(f"")
            parts.append(f"OUTREACH: {analysis.outreach.recommended_contact} ({analysis.outreach.role})")
            parts.append(f"Trigger: {analysis.outreach.trigger}")

        high_conf = sum(1 for cl in evidence.claims if cl.confidence.value == "high")
        med_conf = sum(1 for cl in evidence.claims if cl.confidence.value == "medium")
        low_conf = sum(1 for cl in evidence.claims if cl.confidence.value == "low")
        parts.append(f"")
        parts.append(f"EVIDENCE QUALITY: {high_conf} high-confidence, {med_conf} medium, {low_conf} low")

        # The prompt asks the model to weight recency; without this it was
        # being asked to do that with no dates in front of it.
        parts.append(f"")
        parts.append("EVIDENCE RECENCY:")
        if profile.newest is not None:
            parts.append(f"- Most recent dated evidence: {profile.newest.isoformat()}")
            parts.append(f"- Age of newest evidence: {profile.months_since_newest:.0f} months")
        else:
            parts.append("- No dated evidence found")
        parts.append(f"- Dated items: {profile.dated_count} (undated: {profile.undated_count})")
        parts.append(
            f"- From the last 6 months: {profile.within_6_months}; "
            f"last 12: {profile.within_12_months}; last 24: {profile.within_24_months}"
        )

        return "\n".join(parts)
