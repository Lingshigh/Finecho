import asyncio
import logging
from uuid import uuid4

from agent.graph import build_analysis_graph
from agent.llm import OptionalPolicyLLM
from src.models.schemas import AnalysisRequest, AnalysisResult, AnalysisTask, NodeEvent
from src.repositories.job_repository import InMemoryJobRepository
from src.services.event_bus import EventBus, NodeEventReporter
from src.services.rag_service import GraphRAGService

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(
        self,
        repository: InMemoryJobRepository,
        rag: GraphRAGService,
        llm: OptionalPolicyLLM,
        event_bus: EventBus | None = None,
        policy_bridge=None,
    ) -> None:
        self.repository = repository
        self._event_bus = event_bus
        self.workflow = build_analysis_graph(rag, llm, policy_bridge)
        self._graph_nodes = set(self.workflow.get_graph().nodes) - {"__start__", "__end__"}

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = EventBus()
        return self._event_bus

    async def submit(self, request: AnalysisRequest) -> AnalysisTask:
        task_id = uuid4().hex
        return await self.repository.create(task_id, request)

    async def run(self, task_id: str) -> None:
        task = await self.repository.get(task_id)
        await self.repository.set_running(task_id)
        reporter = NodeEventReporter(task_id, graph_nodes=self._graph_nodes)
        inputs = {
            "task_id": task_id,
            "request": task.request.model_dump(mode="json"),
            "warnings": [],
            "match_attempts": 0,
            "evidence_attempts": 0,
            "max_match_attempts": 3,
            "max_evidence_attempts": 3,
            "lenient_matching": task.request.lenient_matching,
        }
        await self.event_bus.publish(await reporter.on_node_start("analysis_start"))
        try:
            state = await self._run_graph_with_events(inputs, reporter)
            result = AnalysisResult(
                task_id=task_id,
                policy_summary=state["policy_summary"],
                policy_keywords=state["policy_keywords"],
                nodes=state["nodes"],
                edges=state["edges"],
                verdicts=state["verdicts"],
                warnings=state["warnings"],
                report=state.get("report"),
            )
            await self.repository.set_result(task_id, result)
            await self.event_bus.publish(
                NodeEvent(
                    task_id=task_id,
                    type="analysis_complete",
                    node="",
                    label="分析完成",
                    detail=f"完成核验 {len(state['verdicts'])} 家候选公司",
                    progress={"completed": reporter.completed_nodes, "total": len(self._graph_nodes)},
                )
            )
        except Exception as exc:
            logger.exception("Analysis task failed", extra={"task_id": task_id})
            await self.repository.set_error(task_id, str(exc))
            await self.event_bus.publish(
                NodeEvent(task_id=task_id, type="analysis_failed", node="", label="分析失败", detail=str(exc))
            )
        finally:
            await self.event_bus.close(task_id)

    async def _run_graph_with_events(self, inputs: dict, reporter: NodeEventReporter) -> dict:
        state = None
        async for event in self.workflow.astream_events(inputs, version="v2"):
            node = event.get("name")
            kind = event.get("event")
            if node not in self._graph_nodes:
                # 顶层 LangGraph 的 end 事件携带最终状态；路由函数（route_match 等）不产生节点事件。
                if kind == "on_chain_end" and node == "LangGraph":
                    state = event.get("data", {}).get("output")
                    if state is not None:
                        state = dict(state)
                continue
            if kind in {"on_chain_start", "on_node_start"}:
                await self.event_bus.publish(await reporter.on_node_start(node))
            elif kind in {"on_chain_end", "on_node_end"}:
                output = event.get("data", {}).get("output")
                await self.event_bus.publish(
                    await reporter.on_node_end(node, output if isinstance(output, dict) else None)
                )
        if state is None:
            raise RuntimeError("图执行未产生最终状态")
        return state

    async def get(self, task_id: str) -> AnalysisTask:
        return await self.repository.get(task_id)

    async def stream_events(self, task_id: str, target: asyncio.Queue[NodeEvent | None]) -> None:
        """把事件总线的订阅结果转发到目标队列，供 SSE 生成器按行消费。"""
        async for event in self.event_bus.subscribe(task_id):
            target.put_nowait(event)
