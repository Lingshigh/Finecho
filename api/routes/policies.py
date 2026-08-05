from fastapi import APIRouter, BackgroundTasks, Query, Request, status

from api.dependencies import AnalysisServiceDep, PolicyServiceDep
from src.models.policy_schemas import (
    AuthenticityGrade,
    AuthorityLevel,
    PolicyDocument,
    PolicyDocumentType,
    PolicyImpact,
    PolicyLifecycleStatus,
    PolicyLineageResponse,
    PolicyListResponse,
    PolicyStats,
)
from src.models.schemas import AnalysisRequest, TaskAccepted

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    service: PolicyServiceDep,
    q: str = Query(default="", max_length=100),
    authority_level: AuthorityLevel | None = None,
    document_type: PolicyDocumentType | None = None,
    lifecycle_status: PolicyLifecycleStatus | None = None,
    authenticity_grade: AuthenticityGrade | None = None,
    industry: str = Query(default="", max_length=50),
    region: str = Query(default="", max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PolicyListResponse:
    return await service.list(
        q=q,
        authority_level=authority_level,
        document_type=document_type,
        lifecycle_status=lifecycle_status,
        authenticity_grade=authenticity_grade,
        industry=industry,
        region=region,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=PolicyStats)
async def get_policy_stats(service: PolicyServiceDep) -> PolicyStats:
    return await service.stats()


@router.get("/{policy_id}", response_model=PolicyDocument)
async def get_policy(policy_id: str, service: PolicyServiceDep) -> PolicyDocument:
    return await service.get(policy_id)


@router.get("/{policy_id}/lineage", response_model=PolicyLineageResponse)
async def get_policy_lineage(
    policy_id: str, service: PolicyServiceDep
) -> PolicyLineageResponse:
    return await service.lineage(policy_id)


@router.get("/{policy_id}/impacts", response_model=list[PolicyImpact])
async def get_policy_impacts(
    policy_id: str, service: PolicyServiceDep
) -> list[PolicyImpact]:
    return (await service.get(policy_id)).impacts


@router.post(
    "/{policy_id}/analyses",
    response_model=TaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_policy(
    policy_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    policy_service: PolicyServiceDep,
    analysis_service: AnalysisServiceDep,
) -> TaskAccepted:
    policy = await policy_service.get(policy_id)
    analysis_text = policy.content.strip() or "\n".join(
        [policy.summary, policy.title, *(impact.summary for impact in policy.impacts)]
    )
    task = await analysis_service.submit(
        AnalysisRequest(
            policy_title=policy.title,
            policy_text=analysis_text,
            source_url=policy.source_url,
        )
    )
    background_tasks.add_task(analysis_service.run, task.task_id)
    prefix = request.app.state.settings.api_prefix
    return TaskAccepted(
        task_id=task.task_id,
        status=task.status,
        poll_url=f"{prefix}/analyses/{task.task_id}",
        events_url=f"{prefix}/analyses/{task.task_id}/events",
    )
