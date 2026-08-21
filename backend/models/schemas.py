from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class SourceQuality(str, Enum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Source(BaseModel):
    url: str
    title: str
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    source_quality: SourceQuality = SourceQuality.UNKNOWN
    snippet: Optional[str] = None


class Claim(BaseModel):
    statement: str
    claim_type: str = Field(
        description="e.g. funding, expansion, product, leadership, partnership"
    )
    source: Source
    confidence: Confidence = Confidence.MEDIUM
    date_of_event: Optional[str] = None


class Person(BaseModel):
    name: str
    role: str
    relationship: str = Field(
        description="e.g. founder, executive, board_member, investor"
    )
    source: Source
    confidence: Confidence = Confidence.MEDIUM


class CompanyIdentity(BaseModel):
    name: str
    website: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    founded_year: Optional[int] = None


class SearchResult(BaseModel):
    query: str
    url: str
    title: str
    snippet: str
    published_date: Optional[str] = None
    score: Optional[float] = None


class ResearchEvidence(BaseModel):
    company: CompanyIdentity
    claims: list[Claim] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    raw_search_results: list[SearchResult] = Field(default_factory=list)
    researched_at: datetime = Field(default_factory=datetime.utcnow)


class StrategicSignal(BaseModel):
    title: str
    evidence: str = Field(description="The factual basis for this signal")
    interpretation: str = Field(description="What this might mean strategically")
    question: str = Field(description="What to investigate further")
    confidence: Confidence = Confidence.MEDIUM


class StoryAngle(BaseModel):
    angle: str = Field(description="The research question or story hook")
    why_interesting: str
    supporting_evidence: str
    information_gap: str = Field(description="What we don't know yet")


class CaseStudyOpportunity(BaseModel):
    potential_title: str
    central_decision: str
    decision_maker: str
    strategic_tension: str
    evidence_available: str
    missing_information: str
    score: float = Field(ge=0, le=10)
    reasoning: str


class OutreachOpportunity(BaseModel):
    recommended_contact: str
    role: str
    why: str
    trigger: str = Field(description="Recent event that makes outreach timely")
    outreach_thesis: str
    what_you_could_offer: str


class TopPriority(BaseModel):
    topic: str
    why: str


class OpportunityScores(BaseModel):
    story_score: float = Field(ge=0, le=10)
    story_reasoning: str
    case_study_score: float = Field(ge=0, le=10)
    case_study_reasoning: str
    outreach_score: float = Field(ge=0, le=10)
    outreach_reasoning: str
    research_score: float = Field(ge=0, le=10)
    research_reasoning: str

    @computed_field
    @property
    def overall_score(self) -> float:
        return round(
            (self.story_score + self.case_study_score
             + self.outreach_score + self.research_score) / 4,
            1,
        )

    @computed_field
    @property
    def recommendation(self) -> str:
        s = self.overall_score
        if s >= 8.0:
            return "HIGH PRIORITY"
        if s >= 6.0:
            return "WORTH A LOOK"
        if s >= 4.0:
            return "LOW PRIORITY"
        return "SKIP"


class CompanyAnalysis(BaseModel):
    executive_summary: str
    signals: list[StrategicSignal] = Field(default_factory=list)
    story_angles: list[StoryAngle] = Field(default_factory=list)
    case_study: Optional[CaseStudyOpportunity] = None
    outreach: Optional[OutreachOpportunity] = None
    top_priorities: list[TopPriority] = Field(default_factory=list)
    scores: Optional[OpportunityScores] = None


class CompanyBrief(BaseModel):
    evidence: ResearchEvidence
    analysis: CompanyAnalysis
    duration_seconds: float
    from_cache: bool = False
    cached_at: Optional[str] = None


class ScoutRequest(BaseModel):
    query: str = Field(description="Company name or website URL", min_length=1, max_length=200)


class ScoutResponse(BaseModel):
    brief: CompanyBrief
    duration_seconds: float
