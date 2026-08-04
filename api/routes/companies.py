from typing import Annotated

from fastapi import APIRouter, Query

from api.dependencies import GraphRAGServiceDep
from src.core.exceptions import NotFoundError
from src.models.schemas import Evidence

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/{company_id}")
async def get_company(company_id: str, rag: GraphRAGServiceDep) -> dict:
    company = next((item for item in rag.companies if item["id"] == company_id), None)
    if company is None:
        raise NotFoundError(f"公司不存在: {company_id}")
    return company


@router.get("/{company_id}/evidence", response_model=list[Evidence])
async def search_evidence(
    company_id: str,
    rag: GraphRAGServiceDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
) -> list[Evidence]:
    if not any(item["id"] == company_id for item in rag.companies):
        raise NotFoundError(f"公司不存在: {company_id}")
    return rag.retrieve(company_id, q)
