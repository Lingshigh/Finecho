from fastapi import APIRouter, status

from api.dependencies import PolicyServiceDep
from src.models.policy_schemas import (
    PolicyAgentAnalysisResponse,
    PolicyDocumentImportRequest,
    PolicyImportRequest,
    PolicyImportResult,
)

router = APIRouter(prefix="/policy-imports", tags=["policy-imports"])


@router.post("/html", response_model=PolicyImportResult, status_code=status.HTTP_201_CREATED)
async def import_policy_html(
    payload: PolicyImportRequest, service: PolicyServiceDep
) -> PolicyImportResult:
    """Import list-style policy HTML while quarantining obvious news and navigation noise."""

    return await service.import_html(payload)


@router.post(
    "/document",
    response_model=PolicyAgentAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_policy_document(
    payload: PolicyDocumentImportRequest, service: PolicyServiceDep
) -> PolicyAgentAnalysisResponse:
    """Analyze a full policy document with the four-agent guarded pipeline."""

    return await service.import_document(payload)
