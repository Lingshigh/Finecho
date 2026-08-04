from typing import Any, TypedDict

from src.models.schemas import CompanyVerdict, GraphEdge, GraphNode


class AnalysisState(TypedDict, total=False):
    task_id: str
    request: dict[str, Any]
    policy_summary: str
    policy_keywords: list[str]
    industries: list[str]
    products: list[str]
    companies: list[dict[str, Any]]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    verdicts: list[CompanyVerdict]
    warnings: list[str]
