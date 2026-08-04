from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AnalysisRequest(BaseModel):
    policy_title: str = Field(min_length=2, max_length=200)
    policy_text: str = Field(min_length=20, max_length=100_000)
    source_url: HttpUrl | None = None
    target_companies: list[str] = Field(default_factory=list, max_length=50)
    max_depth: int = Field(default=2, ge=1, le=3)
    lenient_matching: bool = False


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal["policy", "industry", "supply_chain", "company"]
    level: int = Field(ge=0, le=3)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = Field(default=1.0, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    company_id: str
    source_type: Literal["annual_report", "inquiry", "announcement", "demo"]
    title: str
    excerpt: str
    year: int | None = None
    source_url: str | None = None
    relevance: float = Field(ge=0, le=1)


class CompanyCandidate(BaseModel):
    """A company selected for fact-checking, with the search path that surfaced it."""

    company_id: str
    name: str
    ticker: str
    reason: str


class CompanyVerdict(BaseModel):
    company_id: str
    company_name: str
    ticker: str
    verdict: Literal["high_confidence", "watch", "hotspot_risk"]
    benefit_probability: float = Field(ge=0, le=1)
    divergence_score: float = Field(ge=0, le=1)
    revenue_exposure: float | None = Field(default=None, ge=0, le=1)
    reasons: list[str]
    evidence: list[Evidence]


class AnalysisResult(BaseModel):
    task_id: str
    policy_summary: str
    policy_keywords: list[str]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    verdicts: list[CompanyVerdict]
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisTask(BaseModel):
    task_id: str
    status: TaskStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request: AnalysisRequest
    result: AnalysisResult | None = None
    error: str | None = None


class TaskAccepted(BaseModel):
    task_id: str
    status: TaskStatus
    poll_url: str


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
