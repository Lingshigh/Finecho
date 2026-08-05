# FinEcho 优化记录 07：SSE 事件流推送（Agent 单步进度实时可见）

> 状态：已实现 · 关联优化：[01 多 Agent 条件路由](optimization-01-langgraph-multi-agent.md) · [02 LLM 对抗式事实核查](optimization-02-llm-adversarial-factcheck.md) · [04 max_depth 层级控制](optimization-04-max-depth.md)
> 日期：2026-08-05

## 一、问题描述

优化前任务状态完全依赖前端轮询：

```
POST /analyses/{task_id}          202 → 返回 task_id
GET  /analyses/{task_id}          ← 前端每隔几秒轮询一次状态与结果
```

存在三个问题：

1. **延迟与噪音**：任务实际只需 1-2 秒完成（演示数据 + 规则解析），轮询要么在已完成任务上空转，要么错过中间过程，用户体验是"提交后白屏，最后突然出结果"；
2. **Agent 过程不可见**：多 Agent 工作流（解构政策 → 扩展产业链 → 匹配公司 → 对抗式核验）每步在做什么，前端完全感知不到，路演时"Agent 思考过程"是核心卖点，却无法展示；
3. **无法提前离场**：前端想展示"当前正在核验哪些公司 / 走了几步 / 是否重试"必须自己推算，成本高且不准确。

## 二、设计：SSE + 内存事件总线

选择 **SSE（Server-Sent Events）** 而非 WebSocket：

| 维度 | SSE | WebSocket |
|---|---|---|
| 方向 | 服务端 → 客户端单向，正合"任务进度推送" | 双向，本场景用不到上行通道 |
| 协议 | 纯 HTTP，复用现有鉴权/限流/CORS 中间件 | 需要握手升级，绕过部分中间件 |
| 复杂度 | 一行 `StreamingResponse` + `text/event-stream` | 连接生命周期、心跳、重连都要自管 |
| 兼容 | 浏览器原生 `EventSource`，自动重连 | 需额外库与降级处理 |

### 事件总线 `EventBus`（发布/订阅）

- 按 `task_id` 隔离的发布/订阅中枢，支持**多客户端订阅同一任务流**；
- 保留任务生命周期内的事件（`max_history=512`），**迟到的订阅者先回放历史**再订阅实时；
- 任务结束（成功/失败）后调用 `close(task_id)`，向所有订阅者发送终止信号并标记关闭——任务完成后新连接的客户端回放完历史即自动结束，不会挂死。

### 事件模型 `NodeEvent`

```json
{
  "task_id": "a1b2...",
  "type": "node_gather_evidence_end",
  "node": "gather_evidence",
  "label": "检索证据",
  "attempt": 2,
  "detail": "汇总 5 家公司证据",
  "progress": { "completed": ["extract_policy", "expand_chain", "match_companies"], "total": 9 },
  "at": "2026-08-05T02:34:09.5Z"
}
```

| 字段 | 含义 |
|---|---|
| `type` | 事件类型：`analysis_start` / `node_<name>_start` / `node_<name>_end` / `analysis_complete` / `analysis_failed` |
| `node` / `label` | 内部节点名 + 中文展示名（供前端直接渲染） |
| `attempt` | 同一节点第几次执行（重试循环时递增，如 `broaden_match`） |
| `detail` | 一句话进度说明，由节点输出折叠而来（只挑数量字段，不刷全量数据） |
| `progress` | `completed` = 已结束节点列表（保留执行顺序），`total` = 全图节点数 |

### 如何接入 LangGraph

把 `AnalysisService.run` 的 `workflow.ainvoke` 换成 **`astream_events(version="v2")`**，按事件流逐条转发：

```python
async for event in self.workflow.astream_events(inputs, version="v2"):
    node = event.get("name")        # 节点名（与 metadata.langgraph_node 等价）
    kind = event.get("event")
    if node not in self._graph_nodes:
        if kind == "on_chain_end" and node == "LangGraph":
            state = event.get("data", {}).get("output")   # 顶层事件携带最终状态
        continue
    if kind in {"on_chain_start", "on_node_start"}:
        await self.event_bus.publish(await reporter.on_node_start(node))
    elif kind in {"on_chain_end", "on_node_end"}:
        await self.event_bus.publish(await reporter.on_node_end(node, event.data.output))
```

三个实现要点：

1. **节点名从 `event["name"]` 取**，且用编译图的真实节点集合 `self.workflow.get_graph().nodes` 过滤——顶层 `LangGraph` 事件与 `route_match`/`route_evidence` 条件路由不产生节点事件，避免混入"伪节点"；
2. **顶层 `LangGraph` 的 `on_chain_end` 携带最终 state**，作为成功结果的唯一来源（`ainvoke` 返回值与它一致）；
3. **节点输出只折叠成一句话**（`_describe`：`核验 N 家候选`、`汇总 N 家公司证据` 等），避免把 `evidence`、`nodes` 等大对象刷进事件流。

### SSE 端点

```
GET /api/v1/analyses/{task_id}/events
```

- 返回 `text/event-stream`，首条事件恒为 `analysis_start`，末条恒为 `analysis_complete`（或 `analysis_failed`）；
- 用 `EventSource` 订阅时按 `event:` 字段分发，浏览器自动重连；
- 15 秒心跳（`: keep-alive`），可经 `heartbeat_interval` 查询参数调整（1-60s）；
- `X-Accel-Buffering: no` 关掉 Nginx 缓冲，保证事件即时到达；
- 客户端断开（`request.is_disconnected()`）即退出生成器，后台消费者任务被取消。

## 三、实现文件

| 文件 | 改动 |
|---|---|
| [src/models/schemas.py](src/models/schemas.py) | 新增 `NodeEvent` 模型；`TaskAccepted` 增加 `events_url` 字段 |
| [src/services/event_bus.py](src/services/event_bus.py) | **新增** `EventBus`（发布/订阅/回放/关闭）与 `NodeEventReporter`（事件流 → NodeEvent） |
| [src/services/analysis_service.py](src/services/analysis_service.py) | `run` 改走 `astream_events` 推送节点事件；新增 `stream_events` 桥接 SSE |
| [api/routes/analyses.py](api/routes/analyses.py) | 新增 `GET /{task_id}/events` SSE 端点；`POST` 响应补 `events_url` |
| [app/lifespan.py](app/lifespan.py) | 应用启动时构造 `EventBus` 注入 `AnalysisService` |
| [tests/test_events.py](tests/test_events.py) | **新增** 事件总线单元测试 + SSE HTTP 全链路测试 |

## 四、验证

### SSE 事件序列实测（新型储能政策）

```
analysis_start
node_extract_policy_start → node_extract_policy_end     # 解构政策
node_expand_chain_start   → node_expand_chain_end       # 扩展产业链
node_match_companies_start→ node_match_companies_end    # 匹配受益公司
node_form_candidate_start → node_form_candidate_end     # 生成核验候选
node_gather_evidence_start→ node_gather_evidence_end    # 检索证据
node_broaden_evidence_start→ node_broaden_evidence_end  # 证据不足，放宽重试（attempt=1）
node_gather_evidence_start→ node_gather_evidence_end    # 放宽后二次检索（attempt=2）
node_adversarial_check_start→ node_adversarial_check_end  # 对抗式核验
node_assemble_graph_start → node_assemble_graph_end     # 装配图谱
analysis_complete
```

可以看到：**证据放宽循环（`broaden_evidence` → `gather_evidence` 重跑）在事件流里完整可见**，前端可据此展示"Agent 每步在做什么"。

### curl 联调

```bash
curl -N http://localhost:8000/api/v1/analyses/{task_id}/events
```

### 单元测试 `tests/test_events.py`

| 测试 | 断言 |
|---|---|
| `test_event_bus_delivers_to_active_subscriber` | 活跃订阅者实时收到 start/end/complete 三类事件 |
| `test_event_bus_replays_history_to_late_subscriber` | 任务已结束，迟到订阅者回放历史后正常结束（不挂死） |
| `test_event_bus_isolates_tasks` | 不同 task_id 事件互不串扰 |
| `test_reporter_tracks_progress_and_attempts` | 进度列表保序、重试 attempt 递增、输出折叠成一句话 |
| `test_events_endpoint_streams_progress_and_complete` | SSE 流推送 `analysis_start` → 节点事件 → `analysis_complete`，且 `POST` 返回 `events_url` |
| `test_events_endpoint_returns_404_for_unknown_task` | 未知 task_id 返回 404 |
| `test_late_subscriber_receives_replayed_events` | 任务完成后连接，收到回放的历史事件 |

### 测试与 lint

```
28 passed, 1 warning
ruff: All checks passed
```

## 五、影响与后续

### 影响

- 前端从"轮询状态"升级为"订阅事件流"，**无需改动既有轮询接口**（`GET /analyses/{task_id}` 保持不变，双通道兼容）；
- Agent 每一步（含重试）在事件流中可见，路演可实时展示"正在检索证据 / 证据不足放宽重试 / 核验候选公司"；
- 任务完成后客户端收到 `analysis_complete` 即可关闭连接，事件历史保证迟到的客户端也能补齐状态。

### 后续方向

1. **连接数上限**：内存事件总线按 `task_id` 隔离，但订阅者无上限。可在 `EventBus` 加每任务最大订阅数，超限拒绝或复用已有回放；
2. **换生产级队列**：多进程部署时内存事件总线失效，可将 `EventBus` 换成 Redis Pub/Sub 或 Arq 的任务事件，接口层无需改动；
3. **结果随流推送**：目前 `analysis_complete` 只带进度，前端仍需 `GET /result` 拉取结果。可让 complete 事件携带完整 result（或 result 下载链接），进一步省一次请求；
4. **事件字段裁剪**：`progress.completed` 目前是节点名列表，可补充每个节点耗时与关键计数，前端做时间线/甘特图。
