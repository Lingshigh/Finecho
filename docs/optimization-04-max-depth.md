# FinEcho 优化记录 04：实现 `max_depth` 控制链条层数

> 状态：已实现 · 关联优化：[01 多 Agent 条件路由](optimization-01-langgraph-multi-agent.md) · [02 LLM 对抗式事实核查](optimization-02-llm-adversarial-factcheck.md) · [03 核验评测基准](optimization-03-evaluation-benchmark.md)
> 日期：2026-08-04

## 一、问题描述

`AnalysisRequest.max_depth`（`ge=1, le=3`）定义于 [schemas.py](src/models/schemas.py)，但代码中从未读取：

- `expand_chain` 永远产出全部 industries + products；
- `assemble_graph` 永远渲染 4 层完整链路（policy → industry → product → company）。

结果：参数是"死配置"。评委若问"max_depth 控制什么"，只能承认它没被实现；前端也无法按用户需求折叠/展开产业链层级。

## 二、设计：链条层数是什么

### 产业链传导的层级模型

突发政策 → 上市公司受益的传导路径，可抽象为四级传导链：

```
level 0  政策事件 (policy)            突发政策/宏观事件
level 1  一级传导行业 (industry)      政策直接扶持的行业（如：储能）
level 2  二级供应链节点 (product)     行业内上游/中游/下游环节（如：锂资源、储能电池、BMS、储能系统）
level 3  关联上市公司 (company)       受益或蹭热点的公司（如：宁德时代、幻影科技）
```

### "链条层数"（max_depth）的两个层面

1. **分析深度**（analysis depth）：Agent 是否解构到供应链节点、是否检索公司并核验。`max_depth` 不应控制这一层——分析深度关乎结果质量，截断会导致核验不完整。
2. **展示深度**（render depth）：图谱向前端渲染到第几层。这是用户可感知的"层数"，也是本优化的落点。

**核心设计决策**：`max_depth` 只控制**展示深度**，分析与核验始终用全量数据。

```
max_depth=1 → policy + industry           （宏观视角：政策影响哪些行业）
max_depth=2 → policy + industry + product （产业视角：传导到哪些供应链环节）
max_depth=3 → 完整 4 层                    （公司视角：哪些公司受益/蹭热点）
```

这一设计有两个优点：

- **判定一致性**：同一政策在 max_depth=1 和 3 下，公司的核验结论完全一致（验证见第四节），保证"折叠图谱不改结论"；
- **语义干净**：depth 是纯展示参数，与评分/检索逻辑解耦，评审追问时有清晰答案。

## 三、实现

### 1. 层级可见集 `agent/nodes.py`

```python
# 图谱节点层级：policy=0, industry=1, supply_chain/product=2, company=3。
def _visible_levels(max_depth: int) -> set[int]:
    return {level for level in range(max_depth + 1)}
```

### 2. `assemble_graph` 裁剪

在组装节点后，按 `max_depth` 过滤，并**去掉指向不可见节点的边**，避免悬空引用：

```python
max_depth = int(request.get("max_depth", 3))
visible = _visible_levels(max_depth)
# ... 组装全部 nodes / edges ...
node_ids = {node.id for node in nodes if node.level in visible}
nodes = [node for node in nodes if node.level in visible]
edges = [edge for edge in edges if edge.source in node_ids and edge.target in node_ids]
```

### 3. 默认值调整 `src/models/schemas.py`

```python
max_depth: int = Field(default=3, ge=1, le=3, description="图谱展示层级：1=政策+行业，2=+供应链，3=完整链路")
```

默认 2 → 3：旧代码默认渲染完整 4 层，改成 3 保持默认行为不变，同时让 `max_depth=2` 有了新的明确含义（只展示到供应链，不连公司）。

## 四、验证

### 单元测试 `tests/test_agent.py::test_max_depth_controls_graph_levels`

| max_depth | 节点类型集合 | 判定一致性 |
|---|---|---|
| 1 | `{policy, industry}` | verdicts 与 depth3 完全一致 |
| 2 | `{policy, industry, supply_chain}` | 同上 |
| 3 | `{policy, industry, supply_chain, company}` | 5 家 |

### 实测输出（储能政策，5 家候选）

```
max_depth=1: nodes=3  edges=2  types={policy:1, industry:2}      verdicts=5
max_depth=2: nodes=7  edges=6  types={..., supply_chain:4}       verdicts=5
max_depth=3: nodes=12 edges=11 types={..., company:5}            verdicts=5
```

三个深度的 `verdicts` 均为 5 家且判定一致 → 展示深度不影响核验结论。

### 测试与 lint

```
14 passed, 1 warning
ruff: All checks passed
```

## 五、影响与后续

### 影响

- `max_depth` 从死配置变为可用的展示层数控制器，前端可按需折叠/展开产业链；
- 默认行为不变（仍渲染完整链路），无回归；
- 新增的 `_visible_levels` 逻辑与层级常量，为后续"按层级着色/按层级统计"打底。

### 后续方向

1. **前端联动**：图谱页提供 depth 切换控件，调用时传 `max_depth`，展示从宏观行业到个股的缩放；
2. **分析深度与展示深度解耦的可视化**：若未来需要"只分析到行业"的轻量模式，可新增 `analysis_depth`，与展示 depth 分开控制；
3. **层级统计**：`max_depth=1` 时可输出"政策 → N 个受影响行业"的概览指标，丰富一页纸简报。
