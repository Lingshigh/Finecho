# FinEcho 优化记录 03：核验评测基准（Benchmark）

> 状态：已实现 · 关联优化：[01 多 Agent 条件路由](optimization-01-langgraph-multi-agent.md) · [02 LLM 对抗式事实核查](optimization-02-llm-adversarial-factcheck.md)
> 日期：2026-08-04

## 一、问题描述

优化前，系统没有任何评测机制：

- 没有标注数据集（ground truth）；
- 没有 precision / recall / F1、混淆矩阵或 AUC 指标；
- `benefit_probability` 与真实受益性之间没有任何对照。

结果：核心卖点"识别蹭热点"无法被量化证明。评委问"准确率多少"时，只能回答"我们做了图谱"，缺乏硬证据。

## 二、方案设计

建立三层评测体系：

```
data/eval_cases.json        ① 标注数据集（人工标注 ground truth）
        │
        ▼
tests/evaluate_verdicts.py ② 评测脚本（跑图 → 比对 → 出指标）
        │
        ▼
报告输出                     ③ 混淆矩阵 + per-class 指标 + hotspot AUC
```

- 每条 case：一份政策 + 一家目标公司 + 人工标注的 `expected_verdict`（high_confidence / watch / hotspot_risk）；
- 评测脚本逐 case 运行完整分析图，得到模型判定后与标注比对；
- 输出三分类混淆矩阵、per-class precision/recall/F1、以及 hotspot 二分类 AUC。

### 为什么 AUC 能"加分"

对黑客松评委，"我们 AUC 0.8+"比"我们有图谱"更有说服力，因为：
1. AUC 是**有标注才有**的指标，说明团队做了评测基建；
2. AUC 对类别不平衡不敏感，能体现"蹭热点识别"这种稀有正类问题的真实鉴别力；
3. 前后对比 AUC 可以量化每次优化的收益（如接入 LLM 核查后 AUC 是否从 0.7 → 0.8）。

## 三、标注数据集（ground truth）

### 1. 如何获取相关标注数据集

**优先推荐（开源、中文、可直接用于政策×公司）**：

| 来源 | 内容 | 适用性 |
|---|---|---|
| 上市公司年报 + 问询函（巨潮资讯/交易所） | 主营构成、收入占比、关联业务 | 标注暴露度、是否蹭热点的**原始依据** |
| 东方财富/同花顺概念板块成分 | 概念标签 → 成分股映射 | 反例标注（板块里大量"伪概念"成分股） |
| 问询函回复（交易所公开披露） | 公司自证"尚无收入/占比低于 5%" | hotspot_risk 的黄金证据 |
| 新闻情感 / 研报标签 | 券商研报的"受益标的"列表 | high_confidence 候选池 |

**进阶（金融 NLP 评测基准）**：
- FinEvent / FinQA 类中文金融事件理解数据（对事件→标的映射有标注）；
- 财报 MD&A 段落级标注（ChEMU / FinFact 类）做证据抽取评测；
- 如需英文对照：FinBench、FLUE 等金融语言理解基准。

### 2. 标注标准（verdict 定义）

| 标注 | 判定条件 | 反例 |
|---|---|---|
| `high_confidence` | 主营构成中**真实存在**该政策传导链对应业务，且收入占比显著（如 >30%） | 收入占比低但被概念带涨 |
| `watch` | 存在部分关联（间接供应链/收入占比 5%-30%）或证据不足 | 关联薄弱仍被热炒 |
| `hotspot_risk` | 收入暴露度极低（<5%）、无相关订单、问询函自证无关联、或业务尚在概念阶段 | 公司声称涉足但财报无支撑 |

**标注要点**：
- 只依据**财报/公告/问询函**等披露事实，不依据股价涨跌（否则引入事后偏差）；
- 每家公司的标注要留 `label_reason`，便于评审复核与审计；
- 正负例都要覆盖：既要"真受益"，也要"蹭热点"和"边缘 watch"，避免只有单边样本。

### 3. 如何评判

**主指标**：
- `accuracy`：三分类总体准确率；
- `hotspot_auc`：将 `watch` + `hotspot_risk` 视为正类、`high_confidence` 为负类的二分类 AUC，衡量"识别非真实受益"的鉴别力；
- per-class `precision / recall / F1`：尤其关注 `hotspot_risk` 的 precision（判了蹭热点就必须准）与 recall（不能漏掉真蹭热点的）。

**辅助指标**：
- `benefit_probability` 与标注序的**秩相关**（Spearman），检验概率排序是否符合直觉；
- 误分类明细（逐 case `MIS` 清单）用于定位系统性盲区。

**当前基线（16 个演示 case 实测）**：

```
总体准确率 (ACC)  : 0.688
Hotspot AUC       : 0.7

Per-class:
  high_confidence  precision=0.600  recall=1.000  f1=0.750  support=6
  watch            precision=0.667  recall=0.500  f1=0.571  support=4
  hotspot_risk     precision=1.000  recall=0.500  f1=0.667  support=6
```

**关键发现**：hotspot_risk 精确率 100%（判了就是对的，幻影科技全中），但召回率仅 50% —— 宁德时代、隆基在"人工智能/半导体"政策下被判 high_confidence/watch，属于**过度宽容**。这正是下一步优化（收紧产品交集判定、让 LLM 核查识别无实质关联）的靶心，优化后可对比 AUC 是否从 0.7 提升。

## 四、实现

### 1. 标注数据集 `data/eval_cases.json`

```json
{
  "_meta": {
    "description": "FinEcho 对抗式核验标注数据集（演示版）。",
    "verdict_definition": { "...": "..." }
  },
  "cases": [
    {
      "case_id": "storage-catl",
      "policy_title": "新型储能示范政策",
      "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
      "target_company": "300750.SZ",
      "expected_verdict": "high_confidence",
      "label_reason": "宁德时代储能电池为核心主业，暴露度 0.89，真实受益"
    }
  ]
}
```

**字段约定**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `case_id` | str | ✅ | 唯一标识，建议 `<政策>-<公司>` |
| `policy_title` | str | ✅ | 政策标题 |
| `policy_text` | str | ✅ | 政策正文（≥20 字） |
| `target_company` | str | ✅ | 公司 id（须在 `companies.json` 存在） |
| `expected_verdict` | enum | ✅ | 三选一：`high_confidence` / `watch` / `hotspot_risk` |
| `label_reason` | str | 建议 | 标注依据，评审可复核 |

### 2. 评测脚本 `tests/evaluate_verdicts.py`

- 读取 `data/eval_cases.json`，逐 case 构造请求并 `graph.ainvoke`；
- 计算混淆矩阵、per-class 指标、AUC（梯形法，处理并列分数）；
- 支持直接运行与 `pytest` 运行；输出报告到 stdout。

```bash
python tests/evaluate_verdicts.py
```

## 五、影响与后续

### 影响

- **可量化证明核心卖点**：有了 ACC / AUC / F1 基线，"识别蹭热点"从口号变成可迭代的指标；
- **定位优化靶心**：16 个 case 暴露"对跨行业公司过度宽容"的盲区，后续改动都有对照基线。

### 后续方向

1. **扩充标注集**：把演示 16 例扩到 100+，覆盖更多政策与公司，保证每类样本均衡；
2. **自动化基准**：把评测接入 CI（如 pytest 标记 `@pytest.mark.eval`），任何改动不劣化 AUC 才可合并；
3. **指标上探**：优化产品交集判定 → 收紧跨行业误判；接入 LLM 核查后复测 AUC，目标从 0.7 提升到 0.85+；
4. **真实数据对接**：从年报/问询函解析主营构成，替代演示 `revenue_exposure`，让 ground truth 有真实财务依据。
