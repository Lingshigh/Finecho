import logging
from uuid import uuid4

from agent.graph import build_analysis_graph
from agent.llm import OptionalPolicyLLM
from src.models.schemas import AnalysisRequest, AnalysisResult, AnalysisTask
from src.repositories.job_repository import InMemoryJobRepository
from src.services.rag_service import GraphRAGService

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(
        self,
        repository: InMemoryJobRepository,
        rag: GraphRAGService,
        llm: OptionalPolicyLLM,
    ) -> None:
        self.repository = repository
        self.workflow = build_analysis_graph(rag, llm)

    async def submit(self, request: AnalysisRequest) -> AnalysisTask:
        task_id = uuid4().hex
        return await self.repository.create(task_id, request)

    async def run(self, task_id: str) -> None:
        task = await self.repository.get(task_id)
        await self.repository.set_running(task_id)
        try:
            state = await self.workflow.ainvoke(
                {
                    "task_id": task_id,
                    "request": task.request.model_dump(mode="json"),
                    "warnings": [],
                    "match_attempts": 0,
                    "evidence_attempts": 0,
                    "max_match_attempts": 3,
                    "max_evidence_attempts": 3,
                    "lenient_matching": task.request.lenient_matching,
                }
            )
            result = AnalysisResult(
                task_id=task_id,
                policy_summary=state["policy_summary"],
                policy_keywords=state["policy_keywords"],
                nodes=state["nodes"],
                edges=state["edges"],
                verdicts=state["verdicts"],
                warnings=state["warnings"],
            )
            await self.repository.set_result(task_id, result)
        except Exception as exc:
            logger.exception("Analysis task failed", extra={"task_id": task_id})
            await self.repository.set_error(task_id, str(exc))

    async def get(self, task_id: str) -> AnalysisTask:
        return await self.repository.get(task_id)
