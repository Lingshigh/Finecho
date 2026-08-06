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
    max_depth: int = Field(default=3, ge=1, le=3, description="图谱展示层级：1=政策+行业，2=+供应链，3=完整链路")
    lenient_matching: bool = False
    industry_hint: str | None = Field(
        default=None,
        max_length=50,
        description="用户指定的行业提示，优先级高于 LLM/规则识别（可选，不填则自动识别）",
    )


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


class ReportRole(BaseModel):
    """产业研报分析视角（角色定位）。"""

    name: str
    perspective: str


class ReportDimension(BaseModel):
    """研报单维度分析（四维度之一）。"""

    name: str
    key: Literal["policy_transmission", "competition", "technology", "supply_chain"]
    summary: str
    key_facts: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ReportFrameworkRow(BaseModel):
    """框架表（SWOT/波特五力/PEST）的单个判定行。"""

    factor: str
    level: Literal["high", "medium", "low"] = "medium"
    statement: str


class ReportFrameworkTable(BaseModel):
    """框架分析表。"""

    name: str
    rows: list[ReportFrameworkRow] = Field(default_factory=list)


class ReportSource(BaseModel):
    """研报数据来源标注。"""

    label: str
    url: str | None = None
    detail: str = ""


class IndustryReport(BaseModel):
    """专业产业研究报告，由 LLM 或规则模板生成，作为 AnalysisResult 的可选字段。"""

    generated_by: Literal["llm", "rule"]
    role: ReportRole
    executive_summary: str
    dimensions: list[ReportDimension] = Field(default_factory=list)
    swot: ReportFrameworkTable | None = None
    porter_five_forces: ReportFrameworkTable | None = None
    pest: ReportFrameworkTable | None = None
    sources: list[ReportSource] = Field(default_factory=list)
    model_name: str = ""


class AnalysisResult(BaseModel):
    task_id: str
    policy_summary: str
    policy_keywords: list[str]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    verdicts: list[CompanyVerdict]
    warnings: list[str] = Field(default_factory=list)
    report: IndustryReport | None = None
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
    events_url: str = ""


class NodeEvent(BaseModel):
    """Agent 单步执行事件：节点开始/结束，携带任务进度与面向展示的说明文本。

    - `type` 形如 `node_extract_policy_start` / `node_extract_policy_end`；
    - `node` / `label` 分别给出内部节点名与中文展示名；
    - `progress.completed` 为已结束的节点列表（保留执行顺序），`total` 为全图节点数；
    - `attempt` 为同一节点在重试循环中第几次执行（从 1 开始）。
    """

    task_id: str
    type: str
    node: str
    label: str = ""
    attempt: int = 1
    detail: str = ""
    progress: dict[str, object] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
