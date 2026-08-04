# FinEcho 优化记录 01：LangGraph 从线性流水线升级为多 Agent 条件路由

> 状态：已实现 · 关联优化：[02 LLM 对抗式事实核查](optimization-02-llm-adversarial-factcheck.md)
> 日期：2026-08-04

## 一、问题描述

优化前 `agent/graph.py` 是 5 个节点的直线流水线：

```
extract_policy → expand_chain → match_companies → verify_companies → assemble_graph
```

没有任何分支、条件路由或循环。申报文件宣称的"核验 Agent 对抗机制""三 Agent 协同"在代码层面只是顺序调用，评委追问 LangGraph 的价值点时缺少实锤。

## 二、方案设计

将核验阶段拆成三个 Agent 节点，并在两处加入条件路由 + 循环回退：

```
extract_policy → expand_chain → match_companies ──route──→ broaden_match（循环放宽，≤3 次）
                                                        ↘ form_candidate
form_candidate → gather_evidence ──route──→ broaden_evidence（循环扩词，≤3 次）
                                           ↘ adversarial_check → assemble_graph
```

| 节点 | 职责 |
|---|---|
| `form_candidate` | 把匹配公司转为待核验候选（带命中路径 reason） |
| `gather_evidence` | 为每家候选检索财报/问询函证据 |
| `adversarial_check` | 带证据对候选做背离度评分与预警（原 verify_companies 拆分） |
| `broaden_match` | 无候选时放宽行业阈值 + 补泛化供应链词重试，仍无则全量纳入样本库兜底 |
| `broaden_evidence` | 证据不足时追加关键词扩召回 |

## 三、实现要点

- `route_match` / `route_evidence` 为模块级纯函数，返回下一个节点名；
- `broaden_match` / `broaden_evidence` 通过 `match_attempts` / `evidence_attempts` + 上限（默认 3）保证**有界终止**，`max_match_attempts` / `max_evidence_attempts` 可注入覆盖；
- 状态机（`AnalysisState`）新增 `candidates` / `evidence` / 重试计数字段。

## 四、调试中修复的真实 Bug

用 `graph.astream()` 逐步追踪状态暴露了三个正确性问题：

1. **回退结果被覆盖**：`broaden_match → match_companies` 回路里，`match_companies` 用初始窄词重查会覆盖放宽产物 → 改为 `broaden_match` 自循环路由；
2. **警告丢失**：`adversarial_check` 返回空 `warnings` 列表覆盖了此前累积的警告 → 改为与 `state["warnings"]` 合并；
3. **证据循环空转**：`gather_evidence` 的 `limit=1 if not relaxed else 3` 导致首次检索相关度不足、误判稀疏 → 统一 `limit=3`，路由改由 `_evidence_sufficient`（相关度 ≥ 0.4）判断。

## 五、验证

- 新增 `tests/test_agent.py`（9 个用例）：正常流、无匹配回退、证据循环、hotspot 判定、上限终止；
- 图结构用 `graph.get_graph()` 断言了条件边与自环；
- 端到端 HTTP 冒烟：储能政策 → 5 家公司判定正确，其中演示公司幻影科技判 `hotspot_risk`，图谱 12 节点 11 边。

```
9 passed
ruff: All checks passed
```
