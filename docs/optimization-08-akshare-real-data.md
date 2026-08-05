# FinEcho 优化记录 08：AKShare 真实数据接入

> 状态：已实现 · 关联优化：[03 核验评测基准](optimization-03-evaluation-benchmark.md) · [05 GraphRAG 图遍历](optimization-05-graphrag-graph-traversal.md)
> 日期：2026-08-05

## 一、问题描述

优化前 `data/companies.json` 与 `data/evidence.json` 全是**手工编造的演示数据**：

- 公司财务数字（`revenue_exposure` / `rd_ratio`）是随手填的固定值；
- 证据是"演示财报摘录"式的一行文本，`source_type` 全部为 `demo`，没有任何来源链接；
- 路演时一追问"这些数字哪来的？"，只能答"演示数据，不构成投资建议"。

## 二、设计：AKShare 免费接口拉取，保留领域本体

目标不是把系统改成实时行情终端，而是**把 `data/` 换血成真实数据**，同时不破坏任何现有逻辑：

| 决策 | 理由 |
|---|---|
| **保留公司池**（宁德/比亚迪/隆基/通威 + 演示热点公司） | `chain_rules.json`、`eval_cases.json`、`test_agent.py` 的断言都围绕这些公司，换池会连带改动评测基线 |
| **保留 `chain_rules.json` / `eval_cases.json`** | 规则匹配与评测 case 依赖领域本体，与财务数字无关 |
| **只替换财务指标 + 证据来源** | 投入产出比最高：`GraphRAGService` 只消费 `data/*.json`，换文件即生效，零代码改动 |
| **`revenue_exposure` 用业务线人工占比近似** | 演示口径：相关业务收入占比由业务构成人工归一化到 [0,1]；真实精确值需读年报分部数据，超出免费接口范围 |

## 三、实现

### 1. `scripts/fetch_real_data.py`（新增）

```
python scripts/fetch_real_data.py            # 写入 data/companies.json + evidence.json
python scripts/fetch_real_data.py --dry-run  # 只预览
```

### 2. 财务指标：东财财务摘要 + 利润表

| 接口 | 字段 | 产出 |
|---|---|---|
| `stock_individual_info_em` | 总市值、行业 | `financials.market_cap_2025` |
| `stock_financial_abstract` | 营业总收入、归母净利润、ROE、毛利率 | `financials.revenue/net_profit/roe` |
| `stock_profit_sheet_by_yearly_em` | **`RESEARCH_EXPENSE`（研发费用）** | `rd_ratio = 研发/营收` |

关键点：东财利润表有 `RESEARCH_EXPENSE` 字段（东财财务摘要没有研发），研发占比用它直接算，无需拼数据。

### 3. 证据：巨潮官方披露公告

`stock_zh_a_disclosure_report_cninfo` 返回公司全部公告（标题 + 链接 + 时间）。
证据选取策略：

1. **优先真实定期报告**：标题含"年度报告 / 半年度报告 / 季度报告"，`source_type = annual_report`；
2. **不足 3 条时**用行业关键词（储能/电池/光伏…）在公告标题里补足，`source_type = announcement`；
3. 每条证据带 `source_url`（巨潮链接），从"演示摘录"升级为"可溯源的真实披露"。

### 4. 顺带修复：RAG 归一化的隐性 bug

数据换血后测试大面积失败，追根因发现 [rag_service.py](src/services/rag_service.py) 的 `retrieve` 有个**被小数据量掩盖的 bug**：

```python
# 原代码：取遍历到的第一条文档分数当除数
max_score = ranked[0][0] if ranked else 0.0
```

原 `evidence.json` 每家公司只有 1 条证据，遍历顺序恰等于分数顺序（唯一），碰巧没爆。
换血后每家 3 条真实证据，**遍历顺序 ≠ 分数顺序**，除数取小 → 归一化后 `relevance > 1`，触发 `Evidence.relevance <= 1` 校验失败。

```python
# 修复：取全量命中的最大分作除数
max_score = max((score for score, _ in ranked), default=0.0)
```

这是"真实数据放大数据量"暴露的潜在缺陷，属正当修复而非演示数据适配。

## 四、验证

### 拉取结果（2025 年报口径）

| 公司 | 营收 | 研发费用 | 研发占比 | ROE | 说明 |
|---|---|---|---|---|---|
| 宁德时代 | 4237 亿 | 221.5 亿 | 5.2% | 24.9% | 数据与公开披露一致 |
| 比亚迪 | 8040 亿 | 579.8 亿 | 7.2% | 15.3% | 研发强度最高 |
| 隆基绿能 | 703 亿 | 15.5 亿 | 2.2% | -11.2% | 光伏周期下行，亏损符合现实 |
| 通威股份 | 841 亿 | 11.1 亿 | 1.3% | -22.0% | 硅料价格暴跌，深度亏损符合现实 |

### 端到端核验（新型储能政策）

```
宁德时代  high_confidence  受益概率 0.86   ← 储能龙头，研发 5.2%，证据充分
通威股份  high_confidence  受益概率 0.76   ← 电池片/硅料切入储能
隆基绿能  watch            受益概率 0.49   ← 光伏公司，对储能政策相关性中等
幻影科技  hotspot_risk     受益概率 0.00   ← 演示热点公司，无相关收入
```

判定分布比纯演示数据更"有层次"（不再是齐刷刷 high_confidence），路演说服力明显增强。

### 测试与 lint

```
28 passed, 1 warning
ruff: All checks passed
评测基线：ACC 0.688、hotspot AUC 0.7（不变）
```

### 数据文件对比

| 维度 | 优化前 | 优化后 |
|---|---|---|
| 证据 source_type | 全 `demo` | `annual_report`（真实年报/季报） |
| 证据来源链接 | 无 | 巨潮公告 URL |
| 财务指标 | 硬编码演示值 | 真实 2025 年报 + 研发占比 |
| evidence 条数 | 5 | 13（每家公司 3 条） |

## 五、影响与后续

### 影响

- **真实感质变**：财务数字、公告标题、来源链接全部可溯源，路演可现场刷新数据演示；
- **零架构改动**：`GraphRAGService` 消费方式不变，仅换 `data/` 内容；
- **评测基线不劣化**：公司池与规则表未动，ACC/AUC 维持原值。

### 后续方向

1. **营收暴露度精确化**：当前 `related_ratio` 是人工业务线占比。可拉东财"主营构成"接口（`stock_zygc_em`）按业务线计算精确占比；
2. **证据正文抽取**：目前证据是公告标题 + 链接。可用巨潮公告正文接口（`stock_notice_report` 详情）抽正文做真实 excerpt，替代"巨潮披露：标题"式文案；
3. **覆盖更多公司**：公司池现在是 4 家，可扩充到 20-30 家覆盖 6 条产业链规则，让"匹配公司"这一步更有画面感；
4. **定时刷新**：给脚本挂 cron / GitHub Actions 每周刷新 `data/`，演示时永远是最新年报数据。
