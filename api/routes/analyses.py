import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.responses import StreamingResponse

from api.dependencies import AnalysisServiceDep
from src.core.exceptions import ConflictError
from src.models.schemas import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisTask,
    NodeEvent,
    TaskAccepted,
    TaskStatus,
)
from src.services.analysis_service import AnalysisService

router = APIRouter(prefix="/analyses", tags=["analysis"])

_HEARTBEAT_INTERVAL_SECONDS = 15.0


def _sse(event: NodeEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"


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
        events_url=f"{request.app.state.settings.api_prefix}/analyses/{task.task_id}/events",
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


@router.get("/{task_id}/events")
async def stream_events(
    task_id: str,
    request: Request,
    service: AnalysisServiceDep,
    heartbeat_interval: float = Query(
        default=_HEARTBEAT_INTERVAL_SECONDS, ge=1, le=60, description="SSE 心跳间隔（秒）"
    ),
) -> StreamingResponse:
    await service.get(task_id)  # 校验任务存在，不存在时抛出 404
    return StreamingResponse(
        _event_stream(request, service, task_id, heartbeat_interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    request: Request, service: AnalysisService, task_id: str, heartbeat_interval: float
) -> AsyncIterator[str]:
    """回放已发生的事件后订阅实时事件；任务完成或客户端断开时结束。

    事件总线的 subscribe 自带历史回放，任务已结束的订阅者在回放完历史后立即返回，
    因此这里无需再从任务快照合成终态事件。
    """
    consumer: asyncio.Task[None] | None = None
    queue: asyncio.Queue[NodeEvent | None] = asyncio.Queue()
    try:
        consumer = asyncio.create_task(
            service.stream_events(task_id, target=queue)
        )
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                break
            yield _sse(event)
            if event.type in {"analysis_complete", "analysis_failed"}:
                break
    finally:
        if consumer is not None:
            consumer.cancel()
            try:
                await consumer
            except asyncio.CancelledError:
                pass
