# FinEcho 优化记录 02：LLM 对抗式事实核查接入对抗式核验

> 状态：已实现 · 关联优化：[01 多 Agent 条件路由与循环回退](optimization-01-langgraph-multi-agent.md)
> 日期：2026-08-04

## 一、问题描述

优化前，`verify_companies` 节点（后更名 `adversarial_check`）的"对抗式核验"是**纯规则打分**：

```python
score = 0.55 * exposure + 0.2 * relevance + 0.15 * rd_strength
score += 0.1 if product_overlap else 0
if exposure < 0.05:
    score -= 0.2
```

- 权重（0.55 / 0.2 / 0.15）与阈值（0.05 / 0.4 / 0.7）硬编码在节点内；
- LLM 只用于 `PolicyExtraction`（政策提取），**从未参与核验**；
- 申报文件宣称的"核验 Agent 对抗机制""AI 辅助金融研究"名不副实——评委演示时一旦追问"AI 到底核验了什么"，只能回答"政策关键词提取用到了模型"。

## 二、方案设计

在保留纯规则 fallback 的前提下，引入**可选的 LLM 事实核查器**，与规则分加权合成：

```
规则分（rule_score 纯函数）
        │ 0.7
        ├────────────┐
        ▼            ▼
   blend_scores ───→ 最终受益概率 + 判定
        ▲
        │ 0.3
  LLM 立场（support / neutral / challenge）
        ▲
        │
   llm.verify()：喂入公司 + 政策 + 候选结论 + 证据片段
        │
   结构化输出 FactCheckResult（stance / rationale / evidence_ids）
```

### 设计要点

1. **可降级**：LLM 未配置、依赖未装、无证据、或 API 调用失败 → `verify()` 返回 `None` → `blend_scores` 退化为纯规则分。与既有 `parse()` 的降级模式一致。
2. **无幻觉输入**：只喂证据库检索出的 `Evidence` 片段，prompt 明确要求"仅依据提供的证据，不得引入外部信息或编造数字"。
3. **可追溯**：LLM 的 `stance` 与 `rationale` 追加进 `reasons` 列表，随 `AnalysisResult` 输出，前端可展示"LLM 为什么质疑这家公司"。
4. **并行**：每家候选的 `llm.verify()` 用 `asyncio.gather` 并发调用，多家公司时避免串行阻塞。

### 立场 → 分数映射

| stance | LLM 分数 | 语义 |
|---|---|---|
| `support` | 0.9 | 证据支持结论，抬高受益概率 |
| `neutral` | 0.5 | 证据不足，保守向 0.5 拉低 |
| `challenge` | 0.25 | 证据矛盾/不支持，显著压低概率 |

合成：`final = 0.7 * rule + 0.3 * llm_score`（`None` 时 `final = rule`）。

## 三、实现

### 1. `agent/llm.py`

新增结构化输出模型与核查方法：

```python
class FactCheckResult(BaseModel):
    stance: Literal["support", "challenge", "neutral"]
    rationale: str = Field(max_length=500)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=10)

class OptionalPolicyLLM:
    async def verify(self, company, policy, claim, evidence) -> FactCheckResult | None:
        # 未配置 / 无证据 → None（fallback）
        # 有配置 → ChatOpenAI.with_structured_output(FactCheckResult) 并注入证据文本
        # 任何异常 → logger.exception + None（fallback）
```

### 2. `agent/nodes.py`

- 抽出模块级纯函数 `rule_score()`：评分逻辑与节点解耦、可单测；
- 新增 `blend_scores()`：规则分与 LLM 立场加权合成；
- `adversarial_check` 改为 async：先 `asyncio.gather` 并行调 `llm.verify()`，再逐家合成、判定、组装 `CompanyVerdict`；
- LLM 的 `stance`/`rationale` 追加进 `reasons`，如 `"LLM 事实核查（challenge）：该业务尚处探索期，未形成合同订单。"`。

## 四、验证

### 单元测试（tests/test_agent.py）

| 测试 | 断言 |
|---|---|
| `test_rule_score_penalizes_low_exposure` | 低暴露度公司 `rule_score < 0.4`，高暴露度 `>= 0.7` |
| `test_blend_scores_llm_challenge_lowers_rule_score` | challenge 拉低、support 拉高、neutral 介于其间、`None` 走纯规则 |
| `test_adversarial_check_llm_support_raises_score` | stub LLM 支持时，低暴露度公司仍判 `hotspot_risk` |
| `test_adversarial_check_llm_challenge_lowers_score` | stub LLM 质疑时，高暴露度公司受益概率被拉低，且 `reasons` 含 LLM 说明 |

### 降级路径验证

- 未配置 `OPENAI_API_KEY`：`verify()` 返回 `None`，端到端冒烟确认 5 家公司判定正确、无 LLM 理由（0 条，符合预期）；
- 配置了无效 key 但未装 `langchain-openai`：`OptionalPolicyLLM.__init__` 捕获 `ImportError` 告警，`verify()` 返回 `None`，安全降级。

### 测试结果

```
13 passed, 1 warning
ruff: All checks passed
```

## 五、影响与后续

### 影响

- **核心卖点落地**："对抗式核验"从规则打分升级为"规则 + LLM 双通道合成"，可向评委展示 `stance`/`rationale` 级可追溯证据链；
- **零风险降级**：无 key / 依赖缺失 / API 故障均回退纯规则，不破坏原有链路。

### 后续方向

1. 把 `_LLM_STANCE_SCORE`、`RULE_WEIGHT` 移到配置或随数据可调，便于调参；
2. 对多家候选的 `llm.verify` 增加超时与重试上限，防止单家卡死整批；
3. 用带标注的评估集（如"哪些公司确属蹭热点"）对比"纯规则 vs 规则+LLM"的精确率/召回率，产出量化指标供路演。
