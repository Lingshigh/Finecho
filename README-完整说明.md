# FinEcho 项目完整说明文档

> 面向突发政策的产业链影响归因与上市公司受益真实性核验服务
> 版本：FinEcho 2.0 · 最后更新：2026-08-06

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [核心功能](#3-核心功能)
4. [技术栈](#4-技术栈)
5. [项目结构](#5-项目结构)
6. [数据模型](#6-数据模型)
7. [API 接口](#7-api-接口)
8. [数据文件规范](#8-数据文件规范)
9. [评测体系](#9-评测体系)
10. [前端说明](#10-前端说明)
11. [快速开始](#11-快速开始)
12. [真实数据接入](#12-真实数据接入)
13. [部署](#13-部署)
14. [优化历程](#14-优化历程)
15. [已知限制与路线图](#15-已知限制与路线图)

---

## 1. 项目概述

FinEcho 是一套**面向突发政策的产业链影响归因与上市公司受益真实性核验服务**。它的核心能力是：

把一段政策文本（或政策库中的真实政策）丢进去，系统会在几十秒内产出：

- 一条**从政策到行业、到供应链环节、再到具体公司**的传导图谱；
- 每家公司一个**受益真实性判定**（高置信受益 / 关注 / 蹭热点风险）；
- 支撑判定的**证据链**（来自哪份财报、哪条公告、哪个来源）；
- 一份**专业产业研究报告**（四维度分析 + SWOT / 波特五力 / PEST + 数据来源标注）。

**目标用户**：卖方/买方研究员、财经媒体与资讯平台、独立投资者与量化团队。

**核心设计哲学**：
- **可解释**：每个结论都带理由与证据，不是黑盒分数；
- **鲁棒**：规则引擎与 LLM 双轨，任何时刻（无 API Key / 依赖缺失 / 模型故障）链路都可用；
- **真实**：企业财务与公告证据来自 AKShare 官方接口，政策来自国务院/部委/地方政府公开页。

---

## 2. 系统架构

### 2.1 整体数据流

```
                    ┌──────────────────────────────────────────┐
   用户输入 ──►      │               前端 (React + Vite)          │
  政策标题+正文      │   常驻导航 / 工作台 / 政策库 / 研报页        │
  [+行业下拉]        └──────────────┬───────────────────────────┘
                                    │ SSE 事件流 / REST
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │            后端 (FastAPI)                  │
                    │  中间件(鉴权/限流/日志) → 路由 → 服务层      │
                    └──────┬───────────────┬───────────────────┘
                           │               │
                           ▼               ▼
              ┌──────────────────┐  ┌──────────────────────┐
              │  LangGraph Agent  │  │   政策事实库          │
              │  产业链归因流水线   │  │   PolicyService      │
              │                  │  │   (582+ 条真实政策)    │
              │  extract_policy  │  │   PolicyBridgeService │
              │  expand_chain    │  └──────────▲───────────┘
              │  match_companies │             │ 关联同行业政策
              │  gather_evidence │             │
              │  adversarial_check│             │
              │  assemble_graph  │             │
              │  compose_report  │             │
              └──────────────────┘             │
                        │                      │
                        ▼                      │
              ┌──────────────────────────────┐ │
              │      产业研究报告 (LLM/规则)   │◄┘
              └──────────────────────────────┘
```

### 2.2 两大子系统

| 子系统 | 说明 | 关联 |
|---|---|---|
| **分析流水线**（AnalysisService + LangGraph） | 处理临时输入的政策，产出图谱/核验/研报 | 通过 `PolicyBridgeService` 关联政策库 |
| **政策事实库**（PolicyService） | 沉淀结构化政策文档（层级/效力/适用范围/影响/关系） | 库内政策可一键送入分析流水线 |

### 2.3 关键设计

- **多 Agent 协作**：核验拆成 form_candidate / gather_evidence / adversarial_check 三个 Agent，条件路由 + 有界循环回退；
- **对抗式事实核查**：LLM 扮演质疑方挑战每个受益宣称，规则分 + LLM 立场加权合成，无 key 时安全降级；
- **GraphRAG 图遍历召回**：候选公司沿产业链图 BFS 传导召回，证据用 TF-IDF 余弦排序；
- **SSE 实时进度**：Agent 每步（含重试）通过事件流实时推送前端。

---

## 3. 核心功能

### 3.1 产业分析工作台（`/workbench`）

1. **提交政策**：输入标题 + 正文（≥20 字），可选填来源链接、指定核验公司、图谱深度（1-3）、宽松匹配、**政策类型/行业下拉**（13 个行业，留空自动识别）；
2. **实时进度**：SSE 事件流展示 Agent 每步执行（解构政策 → 扩展产业链 → 匹配公司 → 检索证据 → 对抗式核验 → 装配图谱 → 生成研报），网络异常自动降级轮询；
3. **分析结果**：
   - **政策摘要** + 关键词 + 风险提示；
   - **产业研究报告**（独立页 `/report`）：四维度 + SWOT/波特五力/PEST + 数据来源，可下载 Markdown 简报；
   - **产业链图谱**：可缩放/拖拽/筛选节点的交互式图谱，节点颜色区分核验结论；
   - **核验结论卡片**：每家公司受益概率/蹭热点风险/业务暴露度 + 理由 + 证据链。

### 3.2 政策事实库（`/policies`）

- **政策目录**：按发文层级（中央/国务院/部委/省/市）、文档类型、行业、地区多维筛选；
- **政策脉络图**：上下位关系（依据/落实/地方细化/解读/引用/替代/废止/重叠/冲突）BFS 图；
- **政策详情**：发文机关、层级、效力状态、文号、适用范围（地区/行业/主体）、产业影响要点（支持/限制/强制）、AI Agent 执行链、可信度分级；
- **HTML 导入**：粘贴政策列表页 HTML，自动隔离新闻/导航噪音/截断标题。

### 3.3 产业研究报告（`/report`）

独立研报页，展示当前分析任务的完整研报：
- **角色定位**：分析师视角
- **四维度**：政策影响传导 / 市场竞争格局 / 技术迭代路径 / 供应链风险
- **三框架**：SWOT / 波特五力 / PEST（强度分级）
- **数据来源**：每个分析点标注来源链接
- **生成方式**：LLM（有 key）或规则模板（无 key），缺维度自动补位

### 3.4 全局常驻导航

顶部导航栏常驻显示（sticky），四项：首页 / 产业分析 / 政策库 / 产业研究报告。点击切换路由并更新选中态（选中项颜色变浅、透明度降低）。

---

## 4. 技术栈

### 后端
| 组件 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+ | 运行时 |
| FastAPI | 0.115+ | Web 框架 |
| LangGraph | 0.2+ | Agent 工作流编排 |
| Pydantic | 2.8+ | 数据模型/校验 |
| NetworkX | 3.3+ | 产业链图结构与 BFS |
| Uvicorn | 0.30+ | ASGI 服务器 |
| httpx | 0.27+ | HTTP 客户端（深圳政策抓取） |

### 前端
| 组件 | 版本 | 用途 |
|---|---|---|
| React | 18.3 | UI 框架 |
| React Router | 6.26 | 路由（/ /workbench /policies /report） |
| Vite | 5.4 | 构建工具 |
| TypeScript | 5.5 | 类型安全 |

### 可选依赖
| 组件 | 用途 |
|---|---|
| `langchain-openai` | LLM 政策解析/核验/研报生成 |
| `chromadb` | （历史遗留，TF-IDF 已替代） |
| `akshare` | 真实企业财务/公告数据拉取 |

---

## 5. 项目结构

```
FinEcho/
├── agent/               LangGraph 状态、节点、工作流与 LLM 适配器
│   ├── graph.py         工作流构建（节点接线 + policy_bridge 注入）
│   ├── nodes.py         9 个节点函数（含 compose_report 研报节点）
│   ├── state.py         AnalysisState 状态定义
│   └── llm.py           OptionalPolicyLLM（解析/核验/研报，可降级）
├── api/                 FastAPI 路由、依赖注入、中间件
│   ├── middleware.py    请求ID/鉴权/限流/请求体限制/安全头
│   ├── router.py        路由汇总
│   └── routes/          analyses/graphs/reports/policies/policy-imports/policy-agents
├── app/                 配置、生命周期、应用入口
│   ├── main.py          FastAPI 应用组装
│   ├── lifespan.py      启动时注入服务（RAG/分析/政策/桥接）
│   └── config.py        pydantic-settings 配置
├── src/                 领域模型、仓库、服务
│   ├── models/          schemas.py + policy_schemas.py
│   ├── repositories/    InMemory 仓库（job/policy）
│   ├── services/        analysis/event_bus/rag/policy/report/policy_bridge/policy_agents
├── scripts/             数据生成脚本
│   ├── fetch_real_data.py          AKShare 刷新公司财务/证据
│   ├── build_policy_seed.py        构建全国政策种子
│   ├── build_industry_companies.py AKShare 动态行业公司池
│   └── build_shenzhen_policy.py    深圳公开政策抓取
├── data/                数据文件（见第 8 节）
├── docs/                13 篇优化/设计文档
├── frontend/            React + Vite 前端
│   └── src/
│       ├── App.tsx      路由 + 常驻导航
│       ├── components/  AppNav / workbench 组件 / landing 组件
│       ├── routes/      Landing / Workbench / PolicyLibrary / Report
│       ├── hooks/       useAnalysis / useGraph
│       └── lib/         http / graphLayout / progress
└── tests/               63 个测试
```

---

## 6. 数据模型

### 6.1 分析侧（`src/models/schemas.py`）

| 模型 | 关键字段 | 说明 |
|---|---|---|
| `AnalysisRequest` | policy_title / policy_text / source_url / target_companies / max_depth / lenient_matching / **industry_hint** | 分析请求（industry_hint 为行业提示） |
| `AnalysisResult` | policy_summary / policy_keywords / nodes / edges / verdicts / warnings / **report** | 分析结果 |
| `CompanyVerdict` | benefit_probability / divergence_score / revenue_exposure / reasons / evidence | 单公司核验结论 |
| `IndustryReport` | generated_by / role / executive_summary / dimensions / swot / porter_five_forces / pest / sources | 产业研报 |

### 6.2 政策侧（`src/models/policy_schemas.py`）

| 模型 | 说明 |
|---|---|
| `PolicyDocument` | 政策文档（文号/机关/层级/类型/效力/范围/影响/Agent 链） |
| `PolicyScope` | 适用范围（地区/行业/主体/条件/期限） |
| `PolicyImpact` | 政策影响（支持/限制/强制/中性 + 产业链节点） |
| `PolicyRelation` | 政策关系（based_on/implements/localizes/interprets/cites/supersedes/repeals/overlaps/conflicts_with） |
| `PolicyAgentRun` | Agent 执行记录（模式/状态/置信度/耗时） |

### 6.3 核心指标定义

```
benefit_probability = 0.7×规则分 + 0.3×LLM立场分（无LLM=规则分）
规则分 = 0.40×暴露度 + 0.25×证据相关度 + 0.15×研发强度 + 0.30×产品交集(或0.12行业交集)
       - 0.10×(无证据) - 0.10×(低暴露)
divergence_score(蹭热点风险) = 独立信号组合（产品缺失/证据不足/低暴露 + 校准带）
verdict 判定 = 高置信(score≥0.7 且 div≤0.4) / 热点(score<0.4 或 div≥0.7) / watch(其余)
```

详见 [docs/optimization-10-core-metrics-rebalance.md](docs/optimization-10-core-metrics-rebalance.md)。

---

## 7. API 接口

基础前缀 `/api/v1`。

### 7.1 分析与图谱

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` / `/ready` | 存活/就绪检查 |
| POST | `/analyses` | 提交政策分析，返回任务 ID + 事件流地址 |
| GET | `/analyses/{task_id}` | 查询任务状态和结果 |
| GET | `/analyses/{task_id}/events` | SSE 事件流（Agent 每步实时推送） |
| GET | `/analyses/{task_id}/result` | 只读取完成结果 |
| GET | `/graphs/{task_id}` | 获取图谱 nodes/edges |
| GET | `/reports/{task_id}.md` | 下载 Markdown 简报 |

### 7.2 公司

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/companies/{id}` | 获取公司基本面 |
| GET | `/companies/{id}/evidence?q=...` | 靶向检索证据 |

### 7.3 政策事实库

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/policies` | 政策列表 + 多维筛选 + facets |
| GET | `/policies/stats` | 汇总统计 |
| GET | `/policies/{id}` | 单篇详情 |
| GET | `/policies/{id}/lineage` | 政策家谱（BFS 关系子图） |
| GET | `/policies/{id}/impacts` | 单篇影响要点 |
| POST | `/policies/{id}/analyses` | 库中政策送入分析流水线 |
| POST | `/policy-imports/html` | 索引导入（含隔离） |
| POST | `/policy-imports/document` | 正文导入（四 Agent 流水线） |
| GET | `/policy-agents/status` | Agent 运行状态 |

---

## 8. 数据文件规范

| 文件 | 内容 | 生成方式 |
|---|---|---|
| `data/companies.json` | 5 家固定公司（宁德/比亚迪/隆基/通威/幻影），含财务与证据 | 演示 / `fetch_real_data.py` |
| `data/companies.dynamic.json` | AKShare 动态行业公司（可选） | `build_industry_companies.py` |
| `data/chain_rules.json` | 6 条产业链规则（光伏/储能/新能源汽车/AI/半导体/机器人） | 手写维护，纯数据可扩 |
| `data/evidence.json` | 13 条真实公告证据（含 source_url） | `fetch_real_data.py` |
| `data/eval_cases.json` | 16 个核验评测 case | 标注 |
| `data/policy_seed.json` | 582 条全国政策（13 行业标签） | `build_policy_seed.py` |
| `data/policy_relations.json` | 47 条政策上下位关系 | `build_policy_seed.py` |
| `data/shenzhen_policy.json` | 深圳政策（region=深圳市，可选） | `build_shenzhen_policy.py` |

---

## 9. 评测体系

### 9.1 核验评测

```bash
python tests/evaluate_verdicts.py
```

输出三分类混淆矩阵、per-class precision/recall/F1、hotspot 二分类 AUC。

**当前基线**（优化后）：**ACC 1.0（16/16）、hotspot AUC 1.0**。

数据：16 个标注 case（储能/光伏/新能源汽车/AI/半导体政策 × 5 家公司）。注意：数据为演示样例，不构成投资建议；评测集是标注演示数据，泛化力需扩大数据集验证。

### 9.2 测试套件

```bash
python -m pytest tests/ -q   # 63 个测试
```

覆盖：Agent 工作流、RAG 图召回、SSE 事件流、政策库筛选/关系、评测脚本、研报生成、行业提示、政策桥接、深圳解析、动态公司加载。

---

## 10. 前端说明

### 10.1 路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | Landing | 首页（营销落地） |
| `/workbench` | 产业分析 | 政策提交 + 图谱 + 核验 |
| `/policies` | 政策库 | 政策目录 + 脉络图 + 详情 |
| `/report` | 产业研究报告 | 完整研报（?task= 指定任务） |

### 10.2 关键组件

- `AppNav.tsx`：全局常驻导航（sticky，四项，选中态变浅半透明）
- `useAnalysis.ts`：工作台状态机（SSE → 轮询降级）
- `GraphCanvas.tsx`：可交互产业链图谱
- `ReportBlock.tsx`：研报区块（角色/维度/框架/来源）
- `PolicyGraph.tsx`：政策脉络图

### 10.3 开发代理

Vite 将 `/api` 代理到 `http://localhost:8000`（后端）。

---

## 11. 快速开始

### 后端

```bash
cd E:\dii\Finecho
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # 加 llm 可选依赖可启用大模型
copy .env.example .env           # 配置 OPENAI_API_KEY（可选）
uvicorn app.main:app --reload    # http://localhost:8000/docs
```

未设置 `OPENAI_API_KEY` 时，系统使用确定性规则解析政策与生成研报，整条链路仍可运行。

### 前端

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

### 跑通一条分析

1. 打开 `http://localhost:5173/workbench`
2. 提交"新型储能示范政策"（预填）
3. 观察 SSE 进度 → 查看图谱/核验/研报

---

## 12. 真实数据接入

### 12.1 AKShare 企业数据

```bash
pip install akshare
python scripts/fetch_real_data.py             # 刷新 5 家公司财务/证据
python scripts/fetch_real_data.py --dry-run   # 只预览
```

### 12.2 AKShare 动态行业公司池

```bash
python scripts/build_industry_companies.py                 # 全部行业
python scripts/build_industry_companies.py --industry 半导体 # 单行业
python scripts/build_industry_companies.py --dry-run
```

生成 `companies.dynamic.json`，重启后端即被 GraphRAG 增量加载。

### 12.3 深圳市政府政策

```bash
python scripts/build_shenzhen_policy.py                 # 抓取并入库
python scripts/build_shenzhen_policy.py --dry-run        # 只预览
python scripts/build_shenzhen_policy.py --source-url <url>
```

生成 `shenzhen_policy.json`（region=深圳市），启动时自动加载。

### 12.4 全国政策种子（22 个机构聚合页）

```bash
python scripts/build_policy_seed.py --source "C:\path\to\html(1)"
```

生成 `policy_seed.json` + `policy_relations.json`。

详见 [docs/optimization-12-multi-source-dynamic-industry.md](docs/optimization-12-multi-source-dynamic-industry.md)。

---

## 13. 部署

### Docker

```bash
docker build -t finecho .
docker run -p 8000:8000 finecho
```

> 注意：Dockerfile 只打包后端 API（uvicorn），前端需单独构建并静态托管（当前未纳入镜像）。

### 生产化路径（当前为演示级）

| 现状 | 生产化建议 |
|---|---|
| InMemoryJobRepository | PostgreSQL + Redis，后台任务换 Arq/Celery |
| InMemoryPolicyRepository | PostgreSQL |
| TF-IDF GraphRAG | ChromaDB 向量召回 + Neo4j 图数据库 |
| API Key 鉴权 | OAuth2/JWT + 可信代理 + 分布式限流 |
| 内存事件总线 | 分布式消息队列 |

---

## 14. 优化历程

项目经历了 12 轮优化（详见 `docs/`）：

| 编号 | 主题 |
|---|---|
| 01 | 多 Agent 条件路由与循环回退 |
| 02 | LLM 对抗式事实核查（安全降级） |
| 03 | 核验评测基准（混淆矩阵/AUC） |
| 04 | max_depth 控制图谱层数 |
| 05 | GraphRAG 图遍历召回 + TF-IDF 排序 |
| 06 | 产业链规则表外置 + 语义化匹配 |
| 07 | SSE 事件流推送 |
| 08 | AKShare 真实数据接入 |
| 09 | 代码审查（30+ 优化项清单） |
| 10 | 核心指标算法重构（产品交集主导 + 独立背离度 + 证据口径打通） |
| 11 | 产业研究报告（LLM+规则混合） |
| 12 | 多源真实数据 + 动态行业链路 |

---

## 15. 已知限制与路线图

### 已知限制
- **公司池规模**：固定 5 家 + 动态 AKShare 公司（需安装 akshare 拉取），新行业需先拉公司数据才能完整匹配；
- **政策正文缺失**：`policy_seed.json` 582 条政策 `content` 为空（仅索引级，需二次核验正文）；
- **评测集小**：16 个演示 case，泛化力有限；
- **内存存储**：任务/政策/限流均在内存，长期运行需清理（见生产化建议）；
- **`_load_real_seed` regions 历史问题**：582 条全国政策 regions 加载后可能为 `[""]`，另起任务修复。

### 路线图
1. 扩大标注数据集，提升核验 ACC/AUC 泛化力；
2. 接真实财报分部收入占比，替换手写 `revenue_exposure`；
3. 政策正文 PDF 流水线（下载/OCR/分段/Embedding）；
4. PostgreSQL/Redis 落地，支持并发；
5. OAuth2/JWT 与分布式限流，从演示走向生产。

---

> **免责声明**：`data/` 中所有公司比例与文本均为演示/测试数据，不构成投资建议，也不能用于真实交易决策。
