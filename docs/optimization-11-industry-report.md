# 产业研究报告功能（LLM+规则混合）

## 概述

把"产业分析"功能的输出从"图谱 + 核验卡片"升级为**专业产业研究报告**，参照行业研究模板：
- **角色定位**：分析师视角
- **四维度**：政策影响传导 / 市场竞争格局 / 技术迭代路径 / 供应链风险
- **分析框架**：SWOT / 波特五力 / PEST
- **数据来源**：每个分析点标注来源（政策 URL / 公告 URL / 公司财务数据）

## 生成方式（LLM + 规则混合）

| 场景 | 结果 |
|---|---|
| 有 `OPENAI_API_KEY` + LLM 正常 | `report.generated_by == "llm"` |
| 无 key / 依赖缺失 / API 超时 / 异常 | `report.generated_by == "rule"`（规则模板兜底） |
| LLM 输出缺维度 | 用规则模板补齐缺失维度（LLM 主体 + 规则补位） |
| 规则模板本身 | 纯同步函数，数据缺失只降级文案、绝不编造数字、不抛错 |

## 数据模型（src/models/schemas.py）

```
IndustryReport
├── generated_by: "llm" | "rule"
├── role: ReportRole { name, perspective }
├── executive_summary: str
├── dimensions: list[ReportDimension]   # 四维度固定顺序
│     ├── name / key(枚举) / summary / key_facts / sources
├── swot / porter_five_forces / pest: ReportFrameworkTable { name, rows }
│     └── rows: ReportFrameworkRow { factor, level(high/medium/low), statement }
├── sources: list[ReportSource] { label, url, detail }
└── model_name: str
```

`AnalysisResult` 追加可选字段 `report: IndustryReport | None = None`（**不改任何现有字段**，契约兼容）。

## 规则模板引擎（src/services/report_service.py）

纯同步函数 `build_rule_report(...)`，输入分析结果字段 + companies 原始 dict：

### 四维度映射
- **政策影响传导**：edges 的 relation 统计 + 政策关键词 + 传导链样例（policy→industry→chain→company）
- **市场竞争格局**：financials.revenue_2025 营收降序排名（跳过无财务公司）、盈利格局、头部集中度、竞对关系
- **技术迭代路径**：rd_ratio 研发强度排序、行业研发均值、产品命中推断技术主线
- **供应链风险**：capacity_constraint 经营约束、上游关键环节、监管问询证据

### 框架表（数据驱动 + 弱推断）
- **SWOT**：优势=高置信公司、劣势=热点风险公司、机会=政策关键词、威胁=低暴露/亏损公司
- **波特五力**：供应商议价=材料依赖公司数、购买者议价=下游环节数、新进入者=低研发公司数、替代品=亏损公司数、竞争强度=共享供应链环节公司对数
- **PEST**：政治=政策关键词+来源、经济=盈利占比+集中度、社会=政策行业标签、技术=研发均值+领先者

`level` 默认 `"medium"`，数据能确定方向才偏离（≥0.7 high / ≥0.4 medium / 其余 low）。

## LLM 生成（agent/llm.py）

`OptionalPolicyLLM.generate_industry_report(...)`：
- 独立 `_report_runner`（with_structured_output(ReportRequest)）
- 输入**预折叠**：companies 转简表、verdicts 取关键字段 + 证据 URL，控 token
- `asyncio.wait_for` 30s 超时，异常返回 None → 规则模板兜底
- 返回的 IndustryReport 结构校验，缺失维度由 `compose_report` 用规则补齐

## 流水线接入（agent/nodes.py / graph.py / state.py）

- `AnalysisState` 加 `report: Any = None`
- `build_nodes` 新增 `compose_report` 节点：LLM 优先、规则兜底、缺维度补位
- `graph.py`：`assemble_graph → compose_report → END`
- `analysis_service.run` 组装 AnalysisResult 时带 `report=state.get("report")`
- `NodeEventReporter._KNOWN_NODES` 补 `"compose_report": "生成研报"`

## 前端（frontend/src）

- `types/api.ts`：ReportRole/ReportDimension/ReportFrameworkRow/ReportFrameworkTable/ReportSource/IndustryReport + `AnalysisResult.report?`
- 新组件 `ReportBlock.tsx`：角色卡、执行摘要、四维度卡片栅格、三张框架表（level 色）、来源列表
- `Workbench.tsx`：摘要之后、图谱之前插入 `<ReportBlock>`
- `workbench.css`：研报样式（`.report-block`/`.report-dimension-grid`/`.level-high|medium|low` 等）

## 报告下载（api/routes/artifacts.py）

`download_report` 在"公司核验结论"与"风险提示"间插入研报章节：分析视角、执行摘要、四维度、三框架表、数据来源列表。

## 测试（tests/test_report.py，9 个用例）

1. 规则模式生成完整结构（dimensions==4、generated_by==rule）
2. 四维度顺序固定
3. 竞争维度按营收排名（比亚迪居首）
4. 供应链维度含 capacity_constraint
5. 幻影科技排除出营收排名、出现在供应链风险
6. 三框架表齐全且 level 合法
7. 空数据不抛异常
8. sources 去重
9. AnalysisResult 序列化含 report 字段

## 验证结果

- **49 个测试全绿**（40 旧 + 9 新），ruff 通过
- **API**：POST 储能政策 → `report.generated_by=="rule"`、四维度齐全、SWOT 4 行/五力 5 行/PEST 4 行、10 个来源
- **内容质量**：比亚迪营收 8039.6 亿居首、盈利格局"2 盈利 2 亏损（隆基/通威）"、头部集中度"中"——全部来自真实财务数据
- **报告下载**：含"产业研究报告"章节 + 真实证据 URL
- **前端**：5173 代理到研报数据、TS 编译通过
