import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import ClassVar

from src.models.schemas import NodeEvent


class EventBus:
    """按 task_id 隔离的节点事件发布/订阅中枢，供 SSE 端点多路复用同一执行流。

    保留任务生命周期内的事件用于回放（新订阅者可收到已发生的历史事件）；
    任务完成后自动结束所有订阅者。
    """

    def __init__(self, max_history: int = 512) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[NodeEvent | None]]] = defaultdict(set)
        self._history: dict[str, deque[NodeEvent]] = defaultdict(lambda: deque(maxlen=max_history))
        self._closed: set[str] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: NodeEvent) -> None:
        async with self._lock:
            self._history[event.task_id].append(event)
            subscribers = list(self._subscribers.get(event.task_id, ()))
        for queue in subscribers:
            queue.put_nowait(event)

    async def subscribe(self, task_id: str) -> AsyncIterator[NodeEvent]:
        """回放已发生的历史事件，随后订阅实时事件；任务已结束时回放完历史即返回。"""
        queue: asyncio.Queue[NodeEvent | None] = asyncio.Queue()
        async with self._lock:
            closed = task_id in self._closed
            if not closed:
                self._subscribers[task_id].add(queue)
            history = list(self._history[task_id])
        if closed:
            # 任务已完成：回放历史事件后直接结束，不订阅（close 会向既有订阅者发终止信号）。
            for event in history:
                yield event
            return
        for event in history:
            queue.put_nowait(event)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            async with self._lock:
                self._subscribers[task_id].discard(queue)

    async def close(self, task_id: str) -> None:
        async with self._lock:
            self._closed.add(task_id)
            queues = self._subscribers.pop(task_id, set())
        for queue in queues:
            queue.put_nowait(None)


class NodeEventReporter:
    """把 LangGraph 的 on_node_start/on_node_end 流转换成统一的节点事件。

    事件模型（详见优化文档 07 第二节）：
      - start  → `node_<name>_start`，推送已完成的节点列表；
      - end    → `node_<name>_end`，推送当前节点（含 attempt 序号与进度信息）；
      - 顶层 LangGraph 的 end 由调用方单独判定，不在此处发出 complete。
    """

    # 需要向前端披露执行细节的节点；未列入的节点仅推送结构事件。
    _KNOWN_NODES: ClassVar[dict[str, str]] = {
        "extract_policy": "解构政策",
        "expand_chain": "扩展产业链",
        "match_companies": "匹配受益公司",
        "broaden_match": "放宽匹配重试",
        "form_candidate": "生成核验候选",
        "gather_evidence": "检索证据",
        "broaden_evidence": "放宽检索重试",
        "adversarial_check": "对抗式核验",
        "assemble_graph": "装配图谱",
        "compose_report": "生成研报",
    }

    def __init__(
        self,
        task_id: str,
        graph_nodes: set[str] | None = None,
        initial_events: list[NodeEvent] | None = None,
    ) -> None:
        self._task_id = task_id
        self._graph_nodes = graph_nodes or set(self._KNOWN_NODES)
        self._completed: list[str] = []
        self._attempts: dict[str, int] = {}
        self._initial_events = initial_events or []

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def initial_events(self) -> list[NodeEvent]:
        return self._initial_events

    @property
    def completed_nodes(self) -> list[str]:
        return list(self._completed)

    def _base(self, type_: str) -> NodeEvent:
        return NodeEvent(
            task_id=self._task_id,
            type=type_,
            node="",
            progress={"completed": list(self._completed), "total": len(self._graph_nodes)},
        )

    async def on_node_start(self, node: str) -> NodeEvent:
        """节点开始：构造 `node_<name>_start` 事件（analysis_start 特例发出 `analysis_start`）。"""
        event = self._base(f"node_{node}_start" if node != "analysis_start" else "analysis_start")
        event.node = node
        event.label = self._KNOWN_NODES.get(node, node)
        event.attempt = self._attempts.get(node, 0) + 1
        event.detail = f"开始：{event.label}"
        self._attempts[node] = event.attempt
        self._initial_events.append(event)
        return event

    async def on_node_end(self, node: str, output: dict | None = None) -> NodeEvent:
        """节点结束：构造 `node_<name>_end` 事件，标记节点已完成。"""
        event = self._base(f"node_{node}_end")
        event.node = node
        event.label = self._KNOWN_NODES.get(node, node)
        event.attempt = self._attempts.get(node, 1)
        if node not in self._completed:
            self._completed.append(node)
        if output:
            event.detail = self._describe(output)
        event.progress = {"completed": list(self._completed), "total": len(self._graph_nodes)}
        self._initial_events.append(event)
        return event

    @staticmethod
    def _describe(output: dict) -> str:
        """把节点输出折叠成一句话进度说明，只挑数量类字段，避免把完整数据刷进事件流。"""
        parts: list[str] = []
        verdicts = output.get("verdicts")
        if isinstance(verdicts, list) and verdicts:
            parts.append(f"核验 {len(verdicts)} 家候选公司")
        evidence = output.get("evidence")
        if isinstance(evidence, dict) and evidence:
            parts.append(f"汇总 {len(evidence)} 家公司证据")
        candidates = output.get("candidates")
        if isinstance(candidates, list) and candidates:
            parts.append(f"生成 {len(candidates)} 个核验候选")
        companies = output.get("companies")
        if isinstance(companies, list) and companies:
            parts.append(f"匹配 {len(companies)} 家公司")
        industries = output.get("industries")
        if isinstance(industries, list) and industries:
            parts.append(f"覆盖 {len(industries)} 个行业")
        return "，".join(parts) if parts else "节点执行完成"
