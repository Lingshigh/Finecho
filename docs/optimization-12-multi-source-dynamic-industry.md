# 多源真实数据 + 动态行业链路

> 状态：设计定稿 · 2026-08-06
> 关联：optimization-08（AKShare）、optimization-11（产业研报）
> 覆盖：动态行业识别、AKShare 动态公司池、深圳政策接入、研报关联政策库、前端行业下拉

## 1. 需求与目标

当前系统只支持"新型储能示范政策"一个演示场景。本次升级目标：

1. **输入的政策类型 + 正文** 决定输出的**行业**，进而关联该行业的**相关政策**和**分析报告**；
2. **AKShare API** 按行业动态拉取企业数据（板块 → 成分股 → 财务 → 公司池）；
3. **深圳市政府数据开放平台**获取深圳产业政策数据（用公开页面 www.sz.gov.cn 代替，无需 appKey）；
4. **不影响前后端功能逻辑**。

**不变式约束**（全程不可破坏）：
- 现有 API 契约字段不变（`AnalysisRequest`/`AnalysisResult` 仅新增可选字段）；
- 现有 49 个测试全绿；
- 评测基线 ACC 1.0 / AUC 1.0 不变；
- `data/companies.json` 现有 5 家公司不动（新增动态公司写入独立文件）。

## 2. 总体架构

```
用户输入：政策标题 + 正文 + [政策类型/行业下拉 → industry_hint]
                        │
                        ▼
          extract_policy（LLM 或规则提取行业/关键词）
                        │
                        ▼
          expand_chain（合并 industry_hint 置首 > LLM > 规则表）
                        │
                        ▼
          match_companies（图遍历召回：industry→company→product）
              ▲                    │
              │              companies 池
        companies.json（5 家固定）   └── companies.dynamic.json（AKShare 动态）
              │
              ▼
          gather_evidence → adversarial_check → assemble_graph
                        │
                        ▼
          compose_report（LLM/规则研报 + PolicyBridge 关联政策库）
              ▲
              │
       PolicyService（policy_seed.json 582 条 + shenzhen_policy.json 深圳市）
```

**从无到有的三条链路**：
- 政策库关联：`PolicyBridgeService` 把库内同行业政策 + 上下位关系注入研报（原本 AnalysisService 从不查 PolicyService）；
- 动态公司池：AKShare 按行业生成 `companies.dynamic.json`，`GraphRAGService` 增量加载；
- 深圳政策：公开页抓取 → `shenzhen_policy.json` → 追加进政策库（region=深圳市）。

## 3. 数据文件规范

| 文件 | 说明 | 生成方式 |
|---|---|---|
| `data/companies.json` | 5 家固定公司（不动） | 演示/`fetch_real_data.py` |
| `data/companies.dynamic.json` | AKShare 动态行业公司 | `build_industry_companies.py` |
| `data/chain_rules.json` | 6 条产业链规则（可扩 keywords） | 手写维护 |
| `data/policy_seed.json` | 582 条全国政策 | `build_policy_seed.py` |
| `data/policy_relations.json` | 47 条政策关系 | `build_policy_seed.py` |
| `data/shenzhen_policy.json` | 深圳政策（region=深圳市） | `build_shenzhen_policy.py` |

动态公司条目结构：
```json
{
  "id": "688981.SH",
  "ticker": "688981.SH",
  "name": "中芯国际",
  "industries": ["半导体", "电子"],
  "products": ["晶圆制造"],
  "revenue_exposure": 0.6,
  "rd_ratio": 0.12,
  "capacity_constraint": "...",
  "financials": { ... },
  "akshare_industry": "半导体",
  "source": "akshare"
}
```

## 4. AKShare 行业 → 公司流水线

接口：
- `ak.stock_board_industry_name_em()`：东财行业板块列表（板块名 → 代码）；
- `ak.stock_board_industry_cons_em(symbol=板块名)`：板块成分股（代码/名称/市值）；
- 财务：`stock_individual_info_em` / `stock_financial_abstract` / `stock_profit_sheet_by_yearly_em`；
- 证据：`stock_zh_a_disclosure_report_cninfo`（巨潮公告）。

流程：
1. `INDUSTRY_TO_BOARD` 映射（政策行业名 → 东财板块名，如 `半导体 → 半导体`、`机器人 → 机器人概念`、`光伏 → 光伏设备`、`人工智能 → AI 概念`）；
2. 板块成分股按总市值取 top N（默认 5）；
3. 对每家公司拉财务 + 证据，`products` 用公司名/东财行业子串匹配规则 products（避免图谱错位），兜底 `products[0]`；
4. 输出 `companies.dynamic.json`。

**降级语义**：`import akshare` 用 `try/except ImportError`；每个接口调用独立 `try/except`，失败打印警告并跳过该板块，不崩。`--dry-run` 只预览不写文件。

## 5. 深圳政策抓取方案

数据源：深圳市政府政策文件公开页（`www.sz.gov.cn` 政策法规栏目，URL 可 `--source-url` 覆盖）。

流程：
1. `httpx` GET → `encoding="utf-8"` 解码；
2. 复用 `policy_service._ITEM_RE` 结构正则提取 `(url, title, date)`；
3. 逐条 `_document_from_index(..., default_level=AuthorityLevel.CITY)` 结构化；
4. **region 覆写**：`scope.regions = ["深圳市"]`（现有 `_document_from_index` 硬编码 `["全国"]`，无法表达深圳市）；
5. 输出 `data/shenzhen_policy.json`。

**容错**：网络错误 → 打印警告 + 返回空列表不 raise；解析失败条目跳过；日期缺失 → None。

加载：`policy_service._load_optional_seed("shenzhen_policy.json")` 复用 `_load_real_seed` 模式追加（文件缺失静默返回）。

## 6. 政策库关联桥接设计（PolicyBridgeService）

新增 `src/services/policy_bridge.py`：

```python
class PolicyBridgeService:
    """把 PolicyService 的库内政策关联进分析流水线。只读查询，不改库。"""
    def __init__(self, policy_service): ...
    async def find_related(self, *, industries, keywords, limit=8):
        """按识别行业 + 关键词查政策库，返回 (matched, relations)。
        全失败/无匹配返回 ([], [])，绝不抛错。"""
```

注入链：
- `app/lifespan.py`：`PolicyBridgeService(policy_service)`；
- `agent/graph.py`：`build_analysis_graph(rag, llm, policy_bridge=None)`（默认 None 保持旧签名）；
- `agent/nodes.py` `compose_report`：调 `find_related`，把命中政策注入研报：
  - **规则分支**：`build_rule_report` 加 `related_policies` 参数，政策影响维度追加"政策库关联"fact，`sources` 追加 `ReportSource(label="政策库", url=...)`；
  - **LLM 分支**：`llm.generate_industry_report` 加 `related_policies` 入参（软调用、默认值兼容）。

## 7. 前端贯通

- `AnalysisRequest` 加 `industry_hint?: string | null`（前后端同步）；
- `SubmitPanel.tsx` 加"政策类型/行业" `<select>`：选项来自 `INDUSTRY_HINT_OPTIONS`（13 行业），首项"自动识别（推荐）"空值；不选 = None = 现状自动识别；
- `agent/nodes.py` `expand_chain`：`industry_hint` 非空时置于 industries 首位（优先级：用户 > LLM > 规则表）。

## 8. 兼容性矩阵

| 现有项 | 受影响? | 原因 |
|---|---|---|
| `AnalysisRequest` 现有 6 字段 | 否 | 仅新增可选字段 |
| 49 个测试 | 否 | `request` 无 industry_hint → None → 行为与现状一致 |
| 评测基线 ACC/AUC | 否 | companies.json 5 家不动 |
| 5 家固定公司 | 否 | 动态公司写独立文件 |
| `find_companies`/`_build_graph` | 否 | 新公司自然入图，逻辑不变 |
| `build_rule_report` 9 测试 | 否 | 新参数默认空 |
| `build_nodes(rag, llm)` 签名 | 否 | policy_bridge 默认 None |

## 9. 验证清单

```bash
cd E:/dii/Finecho
python -m pytest tests/ -q            # 49 旧 + 新增全绿
python tests/evaluate_verdicts.py      # ACC/AUC 不变
python scripts/build_industry_companies.py --dry-run   # 板块→成分→财务预览
python scripts/build_shenzhen_policy.py --dry-run      # 抓取预览
cd frontend && npm run build           # TS 编译
uvicorn app.main:app                   # 手测三场景
```

手测三场景：
1. 选"半导体"提交半导体政策 → 图谱行业节点首现"半导体"、公司为半导体池公司、研报含半导体政策关联；
2. 留空提交储能政策 → 与现状一致；
3. 政策库页面 region=深圳市 过滤命中深圳政策。

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| AKShare 接口字段变动 | try/except 逐接口降级 + `--dry-run` 先验 |
| 东财板块名 ≠ 政策行业名 | `INDUSTRY_TO_BOARD` 映射表 + `--industry` 单拉调试 |
| 动态公司 products 全量塞入致图谱错位 | 名称/行业子串匹配规则 products + 兜底 products[0] |
| 深圳公开页改版/反爬 | URL 可配置 + httpx 失败静默，脚本可重跑 |
| 新行业公司无真实证据 | `retrieve` 空 → `route_evidence` 放宽 → 进核验（已有路径） |
| 政策库 582 条 regions 为 `[""]` 历史问题 | 另起任务修复，不在本计划主路径 |

**回滚**：改动集中在独立新增脚本/文件（`build_industry_companies.py`、`build_shenzhen_policy.py`、`policy_bridge.py`、`companies.dynamic.json`、`shenzhen_policy.json`）+ 少量既有文件（schema 加可选字段、expand_chain 读可选字段、rag_service 增量加载、compose_report 注入）。`git checkout` 既有文件即回滚，新增文件删除即可。
