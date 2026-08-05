import asyncio
from collections import Counter, deque

from src.core.exceptions import NotFoundError
from src.models.policy_schemas import (
    PolicyDocument,
    PolicyFacets,
    PolicyLineageResponse,
    PolicyRelation,
)


class InMemoryPolicyRepository:
    """Policy-domain repository with an API that can later be backed by PostgreSQL."""

    def __init__(self) -> None:
        self._documents: dict[str, PolicyDocument] = {}
        self._relations: list[PolicyRelation] = []
        self._lock = asyncio.Lock()

    async def upsert(self, document: PolicyDocument) -> bool:
        async with self._lock:
            created = document.id not in self._documents
            self._documents[document.id] = document.model_copy(deep=True)
        return created

    async def upsert_many(self, documents: list[PolicyDocument]) -> tuple[int, int]:
        created = 0
        updated = 0
        for document in documents:
            if await self.upsert(document):
                created += 1
            else:
                updated += 1
        return created, updated

    async def get(self, policy_id: str) -> PolicyDocument:
        async with self._lock:
            document = self._documents.get(policy_id)
        if document is None:
            raise NotFoundError(f"政策不存在：{policy_id}")
        return document.model_copy(deep=True)

    async def all(self) -> list[PolicyDocument]:
        async with self._lock:
            documents = list(self._documents.values())
        return [item.model_copy(deep=True) for item in documents]

    async def add_relation(self, relation: PolicyRelation) -> None:
        async with self._lock:
            key = (relation.source_id, relation.target_id, relation.relation)
            for index, existing in enumerate(self._relations):
                if (existing.source_id, existing.target_id, existing.relation) == key:
                    self._relations[index] = relation.model_copy(deep=True)
                    return
            self._relations.append(relation.model_copy(deep=True))

    async def relations(self) -> list[PolicyRelation]:
        async with self._lock:
            return [item.model_copy(deep=True) for item in self._relations]

    async def lineage(self, policy_id: str) -> PolicyLineageResponse:
        await self.get(policy_id)
        documents = {item.id: item for item in await self.all()}
        relations = await self.relations()
        adjacent: dict[str, list[PolicyRelation]] = {}
        for relation in relations:
            adjacent.setdefault(relation.source_id, []).append(relation)
            adjacent.setdefault(relation.target_id, []).append(relation)

        visited = {policy_id}
        queue = deque([policy_id])
        selected_edges: list[PolicyRelation] = []
        while queue:
            current = queue.popleft()
            for relation in adjacent.get(current, []):
                if relation not in selected_edges:
                    selected_edges.append(relation)
                other = (
                    relation.target_id if relation.source_id == current else relation.source_id
                )
                if other in documents and other not in visited:
                    visited.add(other)
                    queue.append(other)

        return PolicyLineageResponse(
            center_id=policy_id,
            nodes=[documents[item_id] for item_id in visited],
            edges=selected_edges,
        )


def build_facets(documents: list[PolicyDocument]) -> PolicyFacets:
    return PolicyFacets(
        authority_levels=dict(Counter(item.authority_level.value for item in documents)),
        document_types=dict(Counter(item.document_type.value for item in documents)),
        lifecycle_statuses=dict(Counter(item.lifecycle_status.value for item in documents)),
        authenticity_grades=dict(
            Counter(item.authenticity_grade.value for item in documents)
        ),
        industries=dict(Counter(industry for item in documents for industry in item.scope.industries)),
        regions=dict(Counter(region for item in documents for region in item.scope.regions)),
    )
