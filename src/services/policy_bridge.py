"""把政策库（PolicyService）的库内政策关联进分析流水线。

分析流水线（AnalysisService/LangGraph agent）原本从不查 PolicyService，
本服务作为只读桥接：按识别行业 + 关键词查政策库，返回命中政策与上下位关系，
供 compose_report 把"关联政策"注入研报上下文。纯查询、无副作用、绝不抛错。
"""

from __future__ import annotations

from datetime import date

from src.models.policy_schemas import PolicyDocument, PolicyRelation
from src.services.policy_service import PolicyService


class PolicyBridgeService:
    def __init__(self, policy_service: PolicyService) -> None:
        self._policy_service = policy_service

    async def find_related(
        self,
        *,
        industries: list[str],
        keywords: list[str],
        limit: int = 8,
    ) -> tuple[list[PolicyDocument], list[PolicyRelation]]:
        """按识别行业 + 关键词查政策库，返回 (命中政策, 涉及的关系)。

        全失败/无匹配返回 ([], [])，绝不抛错（外部数据缺失不影响分析链路）。
        """
        try:
            documents = await self._policy_service.repository.all()
            relations = await self._policy_service.repository.relations()
        except Exception:  # noqa: BLE001 - 外部政策库故障不影响分析链路
            return [], []

        industries = [item for item in industries if item]
        keywords = [item for item in keywords if item]

        def _matches(document: PolicyDocument) -> bool:
            if not industries and not keywords:
                return False
            industry_hit = bool(
                industries and any(ind in document.scope.industries for ind in industries)
            )
            haystack = " ".join(
                [document.title, document.summary, *document.keywords]
            ).lower()
            keyword_hit = bool(keywords and any(kw.lower() in haystack for kw in keywords))
            return industry_hit or keyword_hit

        matched = [document for document in documents if _matches(document)]
        matched.sort(
            key=lambda item: item.publish_date or date.min, reverse=True
        )
        matched = matched[:limit]

        matched_ids = {item.id for item in matched}
        related = [
            relation
            for relation in relations
            if relation.source_id in matched_ids or relation.target_id in matched_ids
        ]
        return matched, related
