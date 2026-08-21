from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class ScoutRequest(BaseModel):
    query: str = Field(description="Company name or website URL")


class ScoutResponse(BaseModel):
    evidence: ResearchEvidence
    duration_seconds: float
