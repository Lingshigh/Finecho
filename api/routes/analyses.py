from fastapi import APIRouter, BackgroundTasks, Request, status

from api.dependencies import AnalysisServiceDep
from src.core.exceptions import ConflictError
from src.models.schemas import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisTask,
    TaskAccepted,
    TaskStatus,
)

router = APIRouter(prefix="/analyses", tags=["analysis"])


@router.post("", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    payload: AnalysisRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    service: AnalysisServiceDep,
) -> TaskAccepted:
    task = await service.submit(payload)
    background_tasks.add_task(service.run, task.task_id)
    return TaskAccepted(
        task_id=task.task_id,
        status=task.status,
        poll_url=f"{request.app.state.settings.api_prefix}/analyses/{task.task_id}",
    )


@router.get("/{task_id}", response_model=AnalysisTask)
async def get_analysis(task_id: str, service: AnalysisServiceDep) -> AnalysisTask:
    return await service.get(task_id)


@router.get("/{task_id}/result", response_model=AnalysisResult)
async def get_result(task_id: str, service: AnalysisServiceDep) -> AnalysisResult:
    task = await service.get(task_id)
    if task.status is not TaskStatus.SUCCEEDED or task.result is None:
        raise ConflictError(
            "分析任务尚未完成", details={"task_id": task_id, "status": task.status.value}
        )
    return task.result
