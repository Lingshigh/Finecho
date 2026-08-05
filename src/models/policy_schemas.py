from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AuthorityLevel(StrEnum):
    CENTRAL = "central"
    STATE_COUNCIL = "state_council"
    MINISTRY = "ministry"
    PROVINCE = "province"
    CITY = "city"
    COUNTY = "county"
    UNKNOWN = "unknown"


class PolicyDocumentType(StrEnum):
    LAW = "law"
    REGULATION = "regulation"
    OPINION = "opinion"
    NOTICE = "notice"
    PLAN = "plan"
    MEASURE = "measure"
    STANDARD = "standard"
    ANNOUNCEMENT = "announcement"
    INTERPRETATION = "interpretation"
    DRAFT = "draft"
    NEWS = "news"
    OTHER = "other"


class PolicyLifecycleStatus(StrEnum):
    DRAFT = "draft"
    EFFECTIVE = "effective"
    AMENDED = "amended"
    REPEALED = "repealed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class AuthenticityGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    QUARANTINED = "quarantined"


class PolicyAgentName(StrEnum):
    DOCUMENT_UNDERSTANDING = "document_understanding"
    SCOPE_EXTRACTION = "scope_extraction"
    IMPACT_ANALYSIS = "impact_analysis"
    RELATION_REASONING = "relation_reasoning"


class PolicyAgentRun(BaseModel):
    agent: PolicyAgentName
    status: Literal["completed", "fallback", "failed"]
    mode: Literal["rule", "llm", "hybrid"]
    summary: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class PolicyClause(BaseModel):
    id: str
    order: int = Field(ge=0)
    heading: str = ""
    text: str


class EvidenceQuote(BaseModel):
    excerpt: str
    clause_ref: str | None = None
    source_url: str | None = None


class PolicyScope(BaseModel):
    regions: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_entities: list[str] = Field(default_factory=list)
    project_stages: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    valid_from: date | None = None
    valid_until: date | None = None
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class PolicyImpact(BaseModel):
    id: str
    title: str
    direction: Literal["support", "restrict", "mandatory", "neutral"] = "neutral"
    action: str
    target: str
    summary: str
    industries: list[str] = Field(default_factory=list)
    chain_nodes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    review_status: Literal["pending", "reviewed", "rejected"] = "pending"


class PolicyDocument(BaseModel):
    id: str
    title: str
    document_number: str | None = None
    issuing_authorities: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = AuthorityLevel.UNKNOWN
    document_type: PolicyDocumentType = PolicyDocumentType.OTHER
    lifecycle_status: PolicyLifecycleStatus = PolicyLifecycleStatus.UNKNOWN
    publish_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    source_name: str
    source_url: str | None = None
    attachment_url: str | None = None
    authenticity_grade: AuthenticityGrade = AuthenticityGrade.C
    is_red_head: bool | None = None
    summary: str = ""
    content: str = ""
    clauses: list[PolicyClause] = Field(default_factory=list)
    scope: PolicyScope = Field(default_factory=PolicyScope)
    impacts: list[PolicyImpact] = Field(default_factory=list)
    agent_runs: list[PolicyAgentRun] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyRelation(BaseModel):
    source_id: str
    target_id: str
    relation: Literal[
        "based_on",
        "implements",
        "localizes",
        "interprets",
        "cites",
        "supersedes",
        "repeals",
        "overlaps",
        "conflicts_with",
    ]
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence: str | None = None


class PolicyFacets(BaseModel):
    authority_levels: dict[str, int] = Field(default_factory=dict)
    document_types: dict[str, int] = Field(default_factory=dict)
    lifecycle_statuses: dict[str, int] = Field(default_factory=dict)
    authenticity_grades: dict[str, int] = Field(default_factory=dict)
    industries: dict[str, int] = Field(default_factory=dict)
    regions: dict[str, int] = Field(default_factory=dict)


class PolicyListResponse(BaseModel):
    items: list[PolicyDocument]
    total: int
    page: int
    page_size: int
    facets: PolicyFacets


class PolicyLineageResponse(BaseModel):
    center_id: str
    nodes: list[PolicyDocument]
    edges: list[PolicyRelation]


class PolicyImportRequest(BaseModel):
    source_name: str = Field(min_length=2, max_length=100)
    authority_name: str = Field(min_length=2, max_length=100)
    html: str = Field(min_length=20, max_length=2_000_000)
    source_url: HttpUrl | None = None
    default_authority_level: AuthorityLevel = AuthorityLevel.UNKNOWN


class PolicyDocumentImportRequest(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=20, max_length=500_000)
    source_name: str = Field(min_length=2, max_length=100)
    authority_name: str = Field(min_length=2, max_length=100)
    source_url: HttpUrl | None = None
    default_authority_level: AuthorityLevel = AuthorityLevel.UNKNOWN
    persist: bool = True


class QuarantinedItem(BaseModel):
    title: str
    url: str | None = None
    reason: str


class PolicyImportResult(BaseModel):
    imported: int
    updated: int
    quarantined: int
    documents: list[PolicyDocument] = Field(default_factory=list)
    quarantine_items: list[QuarantinedItem] = Field(default_factory=list)


class PolicyStats(BaseModel):
    total: int
    formal_documents: int
    pending_review: int
    quarantined: int
    central_documents: int
    local_documents: int


class PolicyAgentAnalysisResponse(BaseModel):
    document: PolicyDocument
    relations: list[PolicyRelation] = Field(default_factory=list)
    persisted: bool = False


class PolicyAgentStatus(BaseModel):
    enabled: bool
    llm_configured: bool
    execution_strategy: str
    agents: list[PolicyAgentName]
