import asyncio

from fastapi.testclient import TestClient

from app.main import app
from src.models.schemas import NodeEvent
from src.services.event_bus import EventBus, NodeEventReporter


def _make_event(task_id: str, type_: str, node: str = "", **overrides: object) -> NodeEvent:
    payload = {"task_id": task_id, "type": type_, "node": node}
    payload.update(overrides)
    return NodeEvent(**payload)


# ---------------------------------------------------------------- EventBus 单元测试


def test_event_bus_delivers_to_active_subscriber() -> None:
    """发布的事件应实时送达订阅者，且完整保留 task_id/type/node。"""

    async def scenario() -> list[str]:
        bus = EventBus()
        reporter = NodeEventReporter("t1", graph_nodes={"extract_policy", "expand_chain"})
        seen: list[str] = []

        async def consume() -> None:
            async for event in bus.subscribe("t1"):
                seen.append(event.type)
                if event.type == "analysis_complete":
                    return

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        await bus.publish(await reporter.on_node_start("extract_policy"))
        await bus.publish(await reporter.on_node_end("extract_policy", {"policy_keywords": ["储能"]}))
        await bus.publish(_make_event("t1", "analysis_complete", label="分析完成"))
        await bus.close("t1")
        await consumer
        return seen

    seen = asyncio.run(scenario())
    assert seen == ["node_extract_policy_start", "node_extract_policy_end", "analysis_complete"]


def test_event_bus_replays_history_to_late_subscriber() -> None:
    """任务已结束时，迟到的订阅者应回放历史事件后正常结束，而不是空转挂死。"""

    async def scenario() -> list[str]:
        bus = EventBus()
        reporter = NodeEventReporter("t2", graph_nodes={"extract_policy"})
        await bus.publish(await reporter.on_node_start("extract_policy"))
        await bus.publish(await reporter.on_node_end("extract_policy"))
        await bus.close("t2")

        late: list[str] = []
        async for event in bus.subscribe("t2"):
            late.append(event.type)
        return late

    assert asyncio.run(scenario()) == ["node_extract_policy_start", "node_extract_policy_end"]


def test_event_bus_isolates_tasks() -> None:
    """不同 task_id 的事件互不串扰，各自维护独立的订阅与历史。"""

    async def scenario() -> None:
        bus = EventBus()
        seen_a: list[str] = []
        seen_b: list[str] = []

        async def consume(task_id: str, seen: list[str]) -> None:
            async for event in bus.subscribe(task_id):
                seen.append(event.type)

        consumer_a = asyncio.create_task(consume("a", seen_a))
        consumer_b = asyncio.create_task(consume("b", seen_b))
        await asyncio.sleep(0.01)
        await bus.publish(_make_event("a", "analysis_start"))
        await bus.publish(_make_event("b", "analysis_start"))
        await bus.close("a")
        await bus.close("b")
        await asyncio.gather(consumer_a, consumer_b)
        assert seen_a == ["analysis_start"]
        assert seen_b == ["analysis_start"]

    asyncio.run(scenario())


def test_reporter_tracks_progress_and_attempts() -> None:
    """进度列表保留执行顺序，重试节点 attempt 递增，输出被折叠成一句话说明。"""

    async def scenario() -> tuple[NodeEvent, NodeEvent]:
        reporter = NodeEventReporter("t3", graph_nodes={"gather_evidence"})
        await reporter.on_node_start("gather_evidence")
        end_first = await reporter.on_node_end("gather_evidence", {"evidence": {"a": [], "b": []}})
        await reporter.on_node_start("gather_evidence")
        end_second = await reporter.on_node_end("gather_evidence", {"evidence": {"a": [], "b": []}})
        return end_first, end_second

    first, second = asyncio.run(scenario())
    assert first.attempt == 1
    assert second.attempt == 2
    assert "汇总 2 家公司证据" in first.detail
    assert first.progress["completed"] == ["gather_evidence"]
    assert second.progress["completed"] == ["gather_evidence"]


# ---------------------------------------------------------------- SSE HTTP 测试


def test_events_endpoint_streams_progress_and_complete() -> None:
    """SSE 流应推送 analysis_start → 节点事件 → analysis_complete，且携带进度。"""
    payload = {
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
    }
    with TestClient(app) as client:
        accepted = client.post("/api/v1/analyses", json=payload)
        assert accepted.status_code == 202
        body = accepted.json()
        task_id = body["task_id"]
        assert body["events_url"] == f"/api/v1/analyses/{task_id}/events"

        types: list[str] = []
        with client.stream("GET", body["events_url"]) as stream:
            for line in stream.iter_lines():
                if line.startswith("event: "):
                    types.append(line[len("event: ") :])
                    if types[-1] in ("analysis_complete", "analysis_failed"):
                        break

        assert types[0] == "analysis_start"
        assert "node_extract_policy_start" in types
        assert "node_adversarial_check_start" in types
        assert types[-1] == "analysis_complete"


def test_events_endpoint_returns_404_for_unknown_task() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/analyses/not-a-task/events")
        assert response.status_code == 404


def test_late_subscriber_receives_replayed_events() -> None:
    """任务完成后才连接 SSE 的客户端，应收到回放的历史事件而非空流或挂死。"""
    payload = {
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
    }
    with TestClient(app) as client:
        accepted = client.post("/api/v1/analyses", json=payload)
        task_id = accepted.json()["task_id"]
        # 等待后台任务完成。
        for _ in range(50):
            task = client.get(f"/api/v1/analyses/{task_id}").json()
            if task["status"] in ("succeeded", "failed"):
                break

        types: list[str] = []
        with client.stream("GET", f"/api/v1/analyses/{task_id}/events") as stream:
            for line in stream.iter_lines():
                if line.startswith("event: "):
                    types.append(line[len("event: ") :])
                    if types[-1] in ("analysis_complete", "analysis_failed"):
                        break
        assert types[0] == "analysis_start"
        assert "analysis_complete" in types
