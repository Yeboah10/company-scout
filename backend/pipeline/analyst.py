from backend.models.schemas import (
    CaseStudyOpportunity,
    CompanyAnalysis,
    Confidence,
    OutreachOpportunity,
    ResearchEvidence,
    StrategicSignal,
    StoryAngle,
    TopPriority,
)
from backend.services.llm import LLMService

ANALYST_SYSTEM_PROMPT = """You are a strategic business analyst specializing in African companies and emerging markets.

Given structured evidence about a company (identity, claims, people), produce a strategic analysis.

You MUST distinguish between:
- VERIFIED FACTS (directly from sources)
- YOUR INTERPRETATION (what the facts might mean)
- OPEN QUESTIONS (what we don't know)

Return ONLY valid JSON in this exact format:
{
    "operational_status": "active|winding_down|defunct|acquired|unknown",
    "status_evidence": "The specific claim that establishes this, or null if unknown",
    "executive_summary": "150 words max. What is this company, what is happening with it, and why might it matter?",
    "signals": [
        {
            "title": "Short signal name (e.g. Geographic Expansion)",
            "evidence": "The factual basis from the research",
            "interpretation": "What this might mean strategically - clearly labeled as interpretation",
            "question": "What should be investigated further",
            "confidence": "high|medium|low"
        }
    ],
    "story_angles": [
        {
            "angle": "A research question or story hook",
            "why_interesting": "Why this angle is worth pursuing",
            "supporting_evidence": "Facts that support this angle",
            "information_gap": "What we don't know yet"
        }
    ],
    "case_study": {
        "potential_title": "e.g. 'Company X: Scaling Across African Markets'",
        "central_decision": "What decision could students/managers analyze?",
        "decision_maker": "Who faces this decision?",
        "strategic_tension": "e.g. Growth vs profitability, Expansion vs complexity",
        "evidence_available": "What information supports writing this case?",
        "missing_information": "What would require interviews or deeper research?",
        "score": 7.5,
        "reasoning": "Why this score"
    },
    "outreach": {
        "recommended_contact": "Full Name",
        "role": "Their title",
        "why": "Why this person is the right contact",
        "trigger": "Recent event making outreach timely",
        "outreach_thesis": "The core reason to reach out",
        "what_you_could_offer": "What value you bring to them"
    },
    "top_priorities": [
        {
            "topic": "If you only investigate three things, investigate this",
            "why": "Brief reason"
        }
    ]
}

Rules:
- Produce 3-5 strategic signals, ranked by importance
- Produce 3-5 story angles
- Top priorities should be exactly 3 items
- The case study score should be honest - not every company deserves a high score
- If there is no credible outreach opportunity, set outreach to null
- Determine operational_status from the evidence before anything else. A
  company that has wound down, shut down or been acquired is a different
  proposition from a trading one, and the rest of the analysis must reflect
  that rather than describing a defunct company as though it were operating.
- If the company is defunct or winding down, set outreach to null: there is
  nobody left to contact. Say so plainly in the executive summary too.
- For African companies, consider the specific market context, not generic Silicon Valley framing
- Be specific and grounded in the evidence, never vague or generic
"""


class CompanyAnalyst:
    def __init__(self, llm: LLMService):
        self.llm = llm

    def analyse(self, evidence: ResearchEvidence) -> CompanyAnalysis:
        evidence_summary = self._build_evidence_summary(evidence)
        data = self.llm.extract_structured(ANALYST_SYSTEM_PROMPT, evidence_summary)

        signals = [
            StrategicSignal(
                title=s["title"],
                evidence=s["evidence"],
                interpretation=s["interpretation"],
                question=s["question"],
                confidence=Confidence(s.get("confidence", "medium")),
            )
            for s in data.get("signals", [])
        ]

        story_angles = [
            StoryAngle(
                angle=a["angle"],
                why_interesting=a["why_interesting"],
                supporting_evidence=a["supporting_evidence"],
                information_gap=a["information_gap"],
            )
            for a in data.get("story_angles", [])
        ]

        case_study = None
        cs = data.get("case_study")
        if cs:
            case_study = CaseStudyOpportunity(
                potential_title=cs["potential_title"],
                central_decision=cs["central_decision"],
                decision_maker=cs["decision_maker"],
                strategic_tension=cs["strategic_tension"],
                evidence_available=cs["evidence_available"],
                missing_information=cs["missing_information"],
                score=cs["score"],
                reasoning=cs["reasoning"],
            )

        outreach = None
        o = data.get("outreach")
        if o:
            outreach = OutreachOpportunity(
                recommended_contact=o["recommended_contact"],
                role=o["role"],
                why=o["why"],
                trigger=o["trigger"],
                outreach_thesis=o["outreach_thesis"],
                what_you_could_offer=o["what_you_could_offer"],
            )

        top_priorities = [
            TopPriority(topic=p["topic"], why=p["why"])
            for p in data.get("top_priorities", [])
        ]

        return CompanyAnalysis(
            executive_summary=data.get("executive_summary", ""),
            operational_status=(data.get("operational_status") or "unknown"),
            status_evidence=data.get("status_evidence"),
            signals=signals,
            story_angles=story_angles,
            case_study=case_study,
            outreach=outreach,
            top_priorities=top_priorities,
        )

    def _build_evidence_summary(self, evidence: ResearchEvidence) -> str:
        c = evidence.company
        parts = [
            f"Company: {c.name}",
            f"Website: {c.website or 'Unknown'}",
            f"Country: {c.country or 'Unknown'}",
            f"Industry: {c.industry or 'Unknown'}",
            f"Founded: {c.founded_year or 'Unknown'}",
            f"Description: {c.description or 'Unknown'}",
            "",
            "PEOPLE:",
        ]

        for p in evidence.people:
            parts.append(f"- {p.name}, {p.role} ({p.relationship}) [confidence: {p.confidence.value}]")

        parts.append("")
        parts.append("CLAIMS (sorted by confidence):")

        sorted_claims = sorted(
            evidence.claims,
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.confidence.value, 3),
        )
        for claim in sorted_claims:
            date_str = f" (Date: {claim.date_of_event})" if claim.date_of_event else ""
            parts.append(
                f"- [{claim.confidence.value.upper()}] {claim.statement}{date_str}\n"
                f"  Type: {claim.claim_type} | Source: {claim.source.title} | URL: {claim.source.url}"
            )

        return "\n".join(parts)
