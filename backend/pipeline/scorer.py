from backend.models.schemas import CompanyAnalysis, OpportunityScores, ResearchEvidence
from backend.services.llm import LLMService

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
        prompt = self._build_scoring_prompt(evidence, analysis)
        data = self.llm.extract_structured(SCORER_SYSTEM_PROMPT, prompt)

        return OpportunityScores(
            story_score=float(data["story_score"]),
            story_reasoning=data["story_reasoning"],
            case_study_score=float(data["case_study_score"]),
            case_study_reasoning=data["case_study_reasoning"],
            outreach_score=float(data["outreach_score"]),
            outreach_reasoning=data["outreach_reasoning"],
            research_score=float(data["research_score"]),
            research_reasoning=data["research_reasoning"],
        )

    def _build_scoring_prompt(self, evidence: ResearchEvidence, analysis: CompanyAnalysis) -> str:
        c = evidence.company
        parts = [
            f"Company: {c.name} ({c.country or 'Unknown'})",
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

        return "\n".join(parts)
