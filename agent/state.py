from typing import Any, TypedDict

from src.models.schemas import CompanyCandidate, CompanyVerdict, GraphEdge, GraphNode


class AnalysisState(TypedDict, total=False):
    task_id: str
    request: dict[str, Any]
    policy_summary: str
    policy_keywords: list[str]
    industries: list[str]
    products: list[str]
    candidates: list[CompanyCandidate]
    companies: list[dict[str, Any]]
    evidence: dict[str, list[Any]]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    verdicts: list[CompanyVerdict]
    warnings: list[str]
    match_attempts: int
    evidence_attempts: int
    max_match_attempts: int
    max_evidence_attempts: int
    lenient_matching: bool
    report: Any = None
