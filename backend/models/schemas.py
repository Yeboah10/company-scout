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

    # PRD principle #5: recent developments count for more. This is applied to
    # the overall score rather than to the four dimensions, because those carry
    # the model's own reasoning and silently contradicting it would be worse
    # than not adjusting at all. Defaults to 1.0 so briefs cached before this
    # existed still load and score exactly as they did.
    recency_factor: float = Field(default=1.0, ge=0.5, le=1.5)
    recency_note: str = ""

    @computed_field
    @property
    def base_score(self) -> float:
        """The four dimensions averaged, before recency is applied."""
        return round(
            (self.story_score + self.case_study_score
             + self.outreach_score + self.research_score) / 4,
            1,
        )

    @computed_field
    @property
    def overall_score(self) -> float:
        return round(min(10.0, max(0.0, self.base_score * self.recency_factor)), 1)

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
    # Whether the company still trades. A defunct company can still make a
    # good story or case study, but it cannot be contacted — the dimensions
    # genuinely diverge, so the status has to travel with the analysis.
    operational_status: str = "unknown"
    status_evidence: Optional[str] = None
    signals: list[StrategicSignal] = Field(default_factory=list)
    story_angles: list[StoryAngle] = Field(default_factory=list)
    case_study: Optional[CaseStudyOpportunity] = None
    outreach: Optional[OutreachOpportunity] = None
    top_priorities: list[TopPriority] = Field(default_factory=list)
    scores: Optional[OpportunityScores] = None


class FoundEmail(BaseModel):
    """An address published somewhere public, with the page that published it."""
    email: str
    kind: str = "personal"          # "personal" | "role"
    source_url: Optional[str] = None
    person: Optional[str] = None


class InferredEmail(BaseModel):
    """A guess built from the company's observed address format.

    Kept in a separate list from found addresses, rather than flagged inside a
    shared one, so nothing downstream can render a guess as a fact by
    forgetting to check a boolean.
    """
    person: str
    email: str
    pattern: str
    # How the guess was arrived at. An address extrapolated from one actually
    # seen at this company is far stronger than one built from what companies
    # generally do, and the reader has to be able to tell them apart.
    basis: str = "observed at this company"


class LinkedInProfile(BaseModel):
    """A LinkedIn lookup result — found or not.

    Every named person gets an entry either way. "We looked and found nothing"
    is information: it tells the user to search manually rather than assume the
    person has no profile. `search_url` makes that one click.

    Only URLs are ever collected. LinkedIn pages are not fetched.
    """
    person: Optional[str] = None
    role: Optional[str] = None
    url: Optional[str] = None
    search_url: Optional[str] = None
    found: bool = False
    is_company_page: bool = False


class ContactInfo(BaseModel):
    company_domain: Optional[str] = None
    pattern: Optional[str] = None
    found: list[FoundEmail] = Field(default_factory=list)
    inferred: list[InferredEmail] = Field(default_factory=list)
    linkedin: list[LinkedInProfile] = Field(default_factory=list)
    note: str = ""


class CompanyBrief(BaseModel):
    evidence: ResearchEvidence
    analysis: CompanyAnalysis
    duration_seconds: float
    from_cache: bool = False
    cached_at: Optional[str] = None
    # Optional so briefs cached before contact discovery existed still load.
    contacts: Optional[ContactInfo] = None

    # Two questions, deliberately kept apart.
    #
    # Averaging them into one number is what let a company that collapsed in
    # 2023 be reported as HIGH PRIORITY: its collapse made a superb story, and
    # that pulled the average up past the fact that nobody is left to email.
    # Both answers matter — the story is why you'd care, the contact route is
    # whether you can act — so the brief reports each and then says what the
    # combination means.

    @computed_field
    @property
    def interest_score(self) -> float:
        """Is this worth your attention? Story, case study and research."""
        s = self.analysis.scores
        if s is None:
            return 0.0
        base = (s.story_score + s.case_study_score + s.research_score) / 3
        return round(min(10.0, max(0.0, base * s.recency_factor)), 1)

    @computed_field
    @property
    def reachability_score(self) -> float:
        """Can you actually act on it? The model's outreach judgement, held to
        what the contact search actually turned up."""
        s = self.analysis.scores
        if s is None:
            return 0.0

        score = s.outreach_score

        # A defunct company has no route in, whatever the story is worth.
        if self.analysis.operational_status in {"defunct", "winding_down"}:
            return 0.0

        c = self.contacts
        if c is None:
            # Contact discovery did not run; the outreach judgement is all
            # there is, and it was made without knowing if anyone is findable.
            return round(min(10.0, score * 0.7), 1)

        if any(f.kind == "personal" for f in c.found):
            pass                      # a named person's published address
        elif c.found:
            score *= 0.8              # only a team inbox
        elif any(l.found and not l.is_company_page for l in c.linkedin):
            score *= 0.6              # no address, but a person on LinkedIn
        elif c.inferred:
            score *= 0.4              # guesses only
        else:
            score *= 0.15             # no route at all

        return round(min(10.0, max(0.0, score)), 1)

    @computed_field
    @property
    def verdict(self) -> str:
        """What the two scores together mean for what to do next."""
        interest = self.interest_score
        reach = self.reachability_score

        if interest >= 6 and reach >= 6:
            return "PURSUE"
        if interest >= 6 and reach >= 3:
            return "WORTH IT — CONTACT IS THE HARD PART"
        if interest >= 6:
            return "WORTH WRITING ABOUT — NO WAY IN"
        if reach >= 6:
            return "REACHABLE BUT THIN"
        return "SKIP"


class ScoutRequest(BaseModel):
    query: str = Field(description="Company name or website URL", min_length=1, max_length=200)


class ScoutResponse(BaseModel):
    brief: CompanyBrief
    share_key: Optional[str] = None
    duration_seconds: float
