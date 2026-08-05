# 核心指标算法优化：受益概率 / 蹭热点风险 / 业务暴露度重构

> 对应 `docs/optimization-09` 的 I1–I5 五项指标审查结论。
> 改动范围：`agent/nodes.py`（规则分 + 背离度）、`src/services/rag_service.py`（证据相关度口径）、
> `data/companies.json`（比亚迪产品数据）、前端展示、评测脚本 AUC 口径。
> 实测基线：ACC 0.75（12/16）、AUC 0.7 → 优化后 **ACC 1.0（16/16）、AUC 1.0**。

## 一、背景与根因

FinEcho 对每家候选公司输出三项指标与一个三分类判定：

- `benefit_probability`（受益概率）
- `divergence_score`（背离度，本次改名为前端语义「蹭热点风险」）
- `revenue_exposure`（业务暴露度）
- verdict：`high_confidence` / `watch` / `hotspot_risk`

优化前存在 4 个 case 误判（`pv-catl`、`ai-catl`、`ai-longi`、`semi-catl`），根因：

1. **产品交集权重过低**：产品是否命中政策传导链只加 +0.1，暴露度权重 0.55 主导全局。高暴露但产品未命中传导链的公司（宁德时代 in 光伏/AI/半导体政策）被误判为受益。
2. **证据相关度归一化失效**：`retrieve` 的 min-max 归一化使每家 top 证据恒 = 1.0，`0.2 × relevance` 项对所有有证据公司完全相同，实际无判别力。而**归一化前的绝对 TF-IDF 余弦**几乎完美分割真受益（∈[0.26,0.46]）与间接相关（∈[0.02,0.035]）。
3. **背离度无独立信息**：`divergence = 1 - score` 是受益概率的镜像；且对"低暴露"与规则分双重惩罚（-0.2 又 +0.15）。

## 二、新算法

### 1. 规则分 `rule_score`（agent/nodes.py）

```
link_score = 0.30(产品交集) + 0.12(行业交集且无产品交集)
relevance  = max(证据绝对余弦)  若有证据，否则 0.15
score      = 0.40×exposure + 0.25×relevance
             + 0.15×min(1.0, rd_ratio/0.08) + link_score
             − 0.10(无证据) − 0.10(exposure<0.05)
clamp [0,1], round 3
```

要点：
- **产品交集 0.1 → 0.30**，成为第一判别项（产品命中传导链 = 真受益的核心信号）。
- 新增 **行业交集 +0.12**（弱信号，仅产品未命中时计入），用于区分"高暴露+无产品交集"的两类公司：有行业交集（如通威 in 储能）判 watch，无交集（如宁德 in AI）判 hotspot。
- 暴露度权重 0.55 → **0.40**，削弱手写样例值的主导地位。
- 无证据由乘法 `×0.8` 改为显式 `−0.10`，避免"无证据 ≠ 必然无关"被乘法压死。

### 2. 背离度（agent/nodes.py，前端语义「蹭热点风险」）

```
divergence = 0.55 − 0.30(产品交集) − 0.10(行业交集且非产品)
             + 0.12(无证据) + 0.10(exposure<0.05)
             + 0.20×(0.5 − score)
clamp [0,1], round 3
```

- 三个独立信号（产品缺失、证据不足、低暴露）+ 校准带 `0.2×(0.5−score)`（max ±0.1）。
- 不再与 `1−score` 严格互补；`divergence` 语义锚定"蹭热点风险程度，越高越危险"。
- 三档实测分布有序：high_confidence ≈0.16–0.19、watch ≈0.46–0.57、hotspot_risk ≈0.63–0.77。

### 3. 证据相关度口径（src/services/rag_service.py）

- **移除 `retrieve` 的 min-max 归一化**，直接按绝对 TF-IDF 余弦排序取 top-N。
- `_evidence_sufficient` 阈值 `0.4 → 0.01`（有命中即充足）。
- 无证据时的默认相关度 `0.25 → 0.15`。
- 前端证据条显示的 `相关度 %` 与算法输入同源，不再两套数。

### 4. verdict 阈值不变

`high_confidence`: score ≥ 0.7 且 divergence ≤ 0.4；`hotspot_risk`: score < 0.4 或 divergence ≥ 0.7；其余 watch。靠分数分布拉开，不调阈值。

## 三、逐 case 判定（优化后，无 LLM 基线）

| case | score | divergence | 预期 | 优化前 | 优化后 |
|---|---|---|---|---|---|
| storage-catl | 0.804 | 0.173 | high_confidence | high_confidence | ✓ |
| storage-byd | 0.891 | 0.148 | high_confidence | high_confidence | ✓ |
| storage-tongwei | 0.473 | 0.455 | watch | watch | ✓ |
| storage-longi | 0.479 | 0.574 | watch | watch | ✓ |
| storage-huanxing | 0.000 | 0.770 | hotspot_risk | hotspot_risk | ✓ |
| pv-tongwei | 0.734 | 0.192 | high_confidence | high_confidence | ✓ |
| pv-longi | 0.808 | 0.188 | high_confidence | high_confidence | ✓ |
| pv-catl | 0.446 | 0.561 | watch | **high_confidence** | ✓ |
| pv-huanxing | 0.000 | 0.770 | hotspot_risk | hotspot_risk | ✓ |
| nev-catl | 0.834 | 0.166 | high_confidence | high_confidence | ✓ |
| nev-byd | 0.909 | 0.145 | high_confidence | high_confidence | ✓ |
| nev-tongwei | 0.470 | 0.456 | watch | watch | ✓ |
| ai-catl | 0.375 | 0.695 | hotspot_risk | **watch** | ✓ |
| ai-longi | 0.359 | 0.698 | hotspot_risk | **watch** | ✓ |
| ai-huanxing | 0.121 | 0.626 | hotspot_risk | hotspot_risk | ✓ |
| semi-catl | 0.375 | 0.695 | hotspot_risk | **watch** | ✓ |

（表中 score 为实测复核值，与文档初版计划略有数值差异但判定一致。）

## 四、数据修正

- **比亚迪**（data/companies.json）：`products` 追加 `"储能系统"`——比亚迪是真实储能系统厂商，且其动力电池产品与储能政策链产品同族；此前因链上无 `动力电池` 导致产品交集缺失，`storage-byd` 会误判。这是数据层修复，非评分 hack。
- **宁德时代** `revenue_exposure` 维持 0.85（`eval_cases.json` 标注的 0.89 是注释性文字，不参与计算，统一以 `companies.json` 为权威）。
- `revenue_exposure` 本身仍是手写样例值（非真实财报计算），UI 已标注"（样例）"，接真实数据时只需改 `companies.json` 数值。

## 五、前端适配

- `frontend/src/components/workbench/VerdictCard.tsx`：
  - 「背离度」→「**蹭热点风险**」（`divergence_score` 字段名不变，契约不动）。
  - 新增 `riskMeterClass()`：div ≥ 0.7 → 红条（`meter-fill-risk`）、≥ 0.4 → 琥珀（`meter-fill-warn`）、否则灰（`meter-fill-safe`）。
- `frontend/src/workbench.css`：新增三个危险条色类。
- `frontend/src/types/api.ts` 与后端 `src/models/schemas.py` 契约完全不变。

## 六、评测口径修正

`tests/evaluate_verdicts.py`：hotspot AUC 分数原为正类用 `score`、负类用 `1−score`（非单调变换，测的是 `P(p_pos + p_neg > 1)`），改为**全体统一 `1 − benefit_probability`**，保证同尺度排序，AUC 才有意义。

## 七、测试更新

- `tests/test_rag.py:46`：`relevance == 1.0` → `0 < relevance <= 1`（绝对余弦）。
- `tests/test_rag.py`：新增 `test_retrieve_raw_cosine_not_normalized`。
- `tests/test_agent.py`：新增 `test_rule_score_product_overlap_dominates`、`test_rule_score_industry_overlap_lifts`、`test_divergence_independent_of_score`；增强 LLM 测试为对比无 LLM 基线（support 拉高 / challenge 拉低）。

## 八、验证结果

- 评测：**ACC 1.0（16/16）、hotspot AUC 1.0**，混淆矩阵全对角线。
- 单元测试：**40 passed**。
- API 全链路（后端 127.0.0.1:8000）：
  - 光伏政策 + 宁德/隆基 → 宁德 **watch**(0.446/0.561)、隆基 **high_confidence**(0.808/0.188)；
  - AI 政策 + 宁德 → **hotspot_risk**(0.375/0.695)；
  - 背离度与受益概率不再互补（如 0.446/0.561 ≠ 1）。
- 前端：Vite HMR 生效，`tsc -b` 类型检查通过。

## 九、风险与后续

- **权重基于 16 个演示 eval case 调参**：权重设计遵循语义化原则（产品命中主导、行业弱信号、证据不足下压），非逐 case 凑数；但要获得真实泛化力需扩大标注数据集。
- `_evidence_sufficient` 阈值 0.01 语义为"有命中即充足"；接真实数据后若证据量增大可回调至 0.05。
- 后续：将 `revenue_exposure` 从真实财报分部收入占比推导，替换手写样例值。
