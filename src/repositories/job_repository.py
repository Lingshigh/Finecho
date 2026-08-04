import asyncio
from datetime import UTC, datetime

from src.core.exceptions import NotFoundError
from src.models.schemas import AnalysisRequest, AnalysisResult, AnalysisTask, TaskStatus


class InMemoryJobRepository:
    """Hackathon-safe repository; replace with Redis/PostgreSQL in production."""

    def __init__(self) -> None:
        self._jobs: dict[str, AnalysisTask] = {}
        self._lock = asyncio.Lock()

    async def create(self, task_id: str, request: AnalysisRequest) -> AnalysisTask:
        task = AnalysisTask(task_id=task_id, status=TaskStatus.QUEUED, request=request)
        async with self._lock:
            self._jobs[task_id] = task
        return task.model_copy(deep=True)

    async def get(self, task_id: str) -> AnalysisTask:
        async with self._lock:
            task = self._jobs.get(task_id)
        if task is None:
            raise NotFoundError(f"分析任务不存在: {task_id}")
        return task.model_copy(deep=True)

    async def set_running(self, task_id: str) -> None:
        await self._update(task_id, status=TaskStatus.RUNNING)

    async def set_result(self, task_id: str, result: AnalysisResult) -> None:
        await self._update(task_id, status=TaskStatus.SUCCEEDED, result=result, error=None)

    async def set_error(self, task_id: str, error: str) -> None:
        await self._update(task_id, status=TaskStatus.FAILED, error=error)

    async def _update(self, task_id: str, **changes: object) -> None:
        async with self._lock:
            task = self._jobs.get(task_id)
            if task is None:
                raise NotFoundError(f"分析任务不存在: {task_id}")
            self._jobs[task_id] = task.model_copy(
                update={**changes, "updated_at": datetime.now(UTC)}
            )
