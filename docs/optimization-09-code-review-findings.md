# FinEcho 优化清单

> 来源：2026-08-05 代码审查（两个后台探索 agent + 前端直接阅读）。
> 根目录 `E:\dii\Finecho`，嵌套副本 `E:\dii\Finecho\Finecho` 被忽略。
> 所有 file:line 均以根目录为准。

## 一、重复 / 死代码

- **`Finecho/Finecho/` 完整副本**：含独立 `.git/` 与主仓库没有的提交（`419db62 agent优化`、`87ad838`），git 中为 untracked。两套代码并行演化，易改错目录。需确认权威工作区；若副本是新版，主目录应对齐，否则删除并加 `.gitignore`。
- **`NodeEventReporter.initial_events` 死代码**（`src/services/event_bus.py:88,94,101-102,124,138`）：全项目无人读取，属历史回放机制残留（EventBus 已有 `_history` 回放）。应删除。
- **`chroma_persist_dir` 死配置**（`app/config.py:22`）：无使用方；`pyproject.toml:21` 的 `rag = ["chromadb>=0.5,<1"]` 死依赖（TF-IDF 已替换 Chroma）。应清理 `.env.example`、`config.py`、`pyproject.toml`。
- **`app_host`/`app_port`**（`config.py:13-14`）：代码内未用。

## 二、明确的 Bug

- **`max_evidence_attempts` 死参数**（`agent/nodes.py:132` vs `agent/state.py:23`、`docs/optimization-01:38`）：硬编码 `evidence_attempts < 1`（最多放宽 1 次），`max_evidence_attempts`（默认 3）从不被读取，与文档承诺/状态字段/测试注入矛盾。二选一修复。
- **SSE `analysis_failed` 的 detail 含换行破坏协议**（`analysis_service.py:79`、`api/routes/analyses.py:25-26`）：`detail=str(exc)` 任意异常文本，若含 `\n` 会破坏 `data:` 帧。需清洗换行或按 SSE 规范续行。
- **SSE 心跳 `wait_for` 丢事件竞态**（`api/routes/analyses.py:100-104`）：`asyncio.wait_for` 超时取消 `queue.get()`，事件在超时瞬间到达会被吞。建议改用 `asyncio.wait + FIRST_COMPLETED` 或守护 task。
- **`extract_policy` 子串匹配与文档矛盾**（`agent/nodes.py:154-155`）：无 LLM 回退用 `word in text` 子串包含（"存储能"误触发"储能"），`chain_rules.json:4` 却声明"不做子串互含"。二选一或补测。
- **`divergence` 双重修正**（`agent/nodes.py:305`）：低暴露公司规则分扣 0.2（`nodes.py:55-56`）又给 divergence 加 0.15，双向下压推高 hotspot_risk。需确认是否有意。

## 九、核心指标算法审查（2026-08-05，基于实测输出）

三个指标的计算链（`agent/nodes.py` + `src/services/rag_service.py`）：
```
benefit_probability  = 0.7×规则分 + 0.3×LLM立场分（无LLM时=规则分）
规则分 = 0.55×暴露度 + 0.2×证据相关度 + 0.15×研发强度 + 0.1×(产品交集)
       - 0.2(暴露度<5%) ×0.8(无证据)
divergence_score     = 1 - benefit_probability（低暴露再 +0.15）
verdict              = 高置信(score≥0.7 且 div≤0.4) / 热点(score<0.4 或 div≥0.7) / watch(其余)
```

### I1. 暴露度数据与评分口径冲突（高）
- `data/companies.json` 宁德时代 `revenue_exposure=0.85`，但 `data/eval_cases.json:18` 标注"暴露度 0.89"，同一家公司两处不一致。
- 通威股份在储能政策下暴露度 0.8、证据相关度 100%，`rule_score≈0.76` 本应 `high_confidence`，实测被判 `watch`——因产品无交集拿不到 +0.1。verdict 单点阈值(0.7/0.4)对边界公司极不稳定（通威/隆基是活例）。
- `revenue_exposure` 本身是手写样例值（`scripts/fetch_real_data.py:176` 也用常量 `related_ratio`），不是真实财报计算，整条指标链的输入仍是演示数据。

### I2. `divergence` 是受益概率的镜像，非独立指标（高）
- 前端把背离度画成独立进度条（`frontend/src/components/workbench/VerdictCard.tsx:56`），但 `divergence = 1 - score`（低暴露 +0.15）。用户看到"受益 80%/背离 20%"两根互补条，无任何说明它们是反义关系。背离度没有独立信息量。
- +0.15 与规则分的 -0.2 对同一"低暴露"信号双重惩罚，会把"高置信但低暴露"的真受益公司硬推向 hotspot_risk。

### I3. 证据相关度口径断裂（中）
- `retrieve` 做了 min-max 归一化（`rag_service.py:170`），每家 top1 证据必然 = 1.0。`adversarial_check` 取 top-3 证据的最大值作 `relevance`（`nodes.py:296`），导致"有证据的公司 relevance 恒=1.0"，`0.2×relevance` 项对所有有证据公司完全相同，实际失效。
- 前端展示的"相关度 25%"是归一化前的 TF-IDF 绝对分，与评分用的 1.0 不是同一套数。

### I4. 图距离分数与暴露度量纲相加（中）
- `find_companies` 用 `graph_score(0/0.6/1.0) + revenue_exposure(0~1)` 直接相加排序（`rag_service.py:113-116`），无量纲分数与概率硬加，排序含义不明确。

### I5. 阈值隐式依赖归一化（低）
- `_evidence_sufficient` 的 `relevance>=0.4`（`nodes.py:125`）、评分相关度默认 0.25（`nodes.py:296`）都建立在天真的归一化之上；一旦去掉 min-max，`0.4`/`0.25` 立即失效。

## 三、内存 / 性能

- **`InMemoryJobRepository._jobs` 无限增长**（`src/repositories/job_repository.py:12`）：任务+完整结果永不清理，需 TTL/上限/delete。
- **`EventBus._history`/`_closed` 永不回收**（`src/services/event_bus.py:18,54-59`）：close 后历史仍保留，uuid 不可复用，线性增长。close 后历史已无人能订阅，可安全清空。
- **RateLimit `hits` 以可伪造 `X-Forwarded-For` 为 key 且永不清理**（`api/middleware.py:89,93`）：攻击者可伪造随机 IP 撑爆内存并绕过限流。
- **`PolicyService.list`/`stats`/`lineage` 每次全量加载**（`policy_service.py:112,156`、`policy_repository.py:62-90`）：样本小无感，换 PostgreSQL 前需缓存/分页。
- **`import_html` 每导入一篇 O(N) prompt 开销**（`policy_service.py:203`、`policy_agents.py:140-144`）。
- **`self._quarantine` 无限增长**（`policy_service.py:87`）。

## 四、安全

- **`X-Request-ID` 信任客户端 + 日志注入面**（`api/middleware.py:17,22`、`errors.py`）：需白名单字符集或忽略客户端值。
- **`BodyLimitMiddleware` 只查 `Content-Length`**（`api/middleware.py:52-63`）：chunked/伪造头形同虚设；且 `max_body_bytes`(2MB) 与 `html` 字段(2M 字符≈6MB) 冲突，合法导入会被 413 拒。
- **API 默认无密钥**（`config.py:17`）：`.env.example` 默认空，业务端点全公开；`/redoc` 未进 `main.py:42` 排除清单。
- **`X-Forwarded-For` 无可信反代剥离**（`middleware.py:93`）。

## 五、评测与测试

### 评测（Critical）
- **数据泄漏/标注循环依赖**（`data/eval_cases.json:113-115,137-138`）：label_reason 直接写"模型当前判 X 属过度宽容"，标注看了模型输出才定，非独立事实。ACC 0.688 / AUC 0.7 不能当真实鉴别力。
- **AUC 分数变换错误**（`tests/evaluate_verdicts.py:121-123`）：正类用 `benefit_probability`、负类用 `1 - benefit_probability`，非全局单调变换，测的是 `P(benefit_pos + benefit_neg > 1)`。应统一用 `1 - benefit_probability` 作为 hotspot 分数。
- **目标公司无判定静默回退 `watch`**（`evaluate_verdicts.py:99-102`）：污染混淆矩阵与 AUC，应显式报错。
- **空 cases 除零**（`evaluate_verdicts.py:137`）；**逐 case 串行重建全图**（L2）。

### 测试
- **LLM 核验测试断言恒真/无判别力**（`tests/test_agent.py:216-232`）：`challenge` 断言上限 0.95，blend 最大 0.775 恒 `< 0.95`；support 测试未对比无 LLM 基线。
- **关键路径零测试**（H4）：中间件(401/429/413)、companies 路由、失败路径(`set_error`/500)、result 端点 Conflict、persist=True、LLM parse/回退分支、`watch` 判定、`route_match`/`find_companies(targets)`、`broaden_match` 全量兜底。
- **时序脆弱**（M1）：`asyncio.sleep(0.01)` 注册订阅者、50 次轮询无 sleep/超时、test_api 提交即断言 succeeded。
- **测试与手调数据强耦合**（M2）：硬编码"宁德时代第一"等，`fetch_real_data.py` 换血即破坏；无数据完整性校验测试。
- **`pyproject.toml`**（M3）：`httpx` 在运行时依赖（应入 dev）；`evaluate_verdicts.py` 无 test 函数按文档跑得 "no tests ran"；无 pytest-cov/filterwarnings。

## 六、前端

- **`useAnalysis.ts` failed 分支未 stopPolling**（`src/hooks/useAnalysis.ts` 内 analysis_failed 分支）：与轮询存在短暂竞态，应显式 stop。
- **`http.ts` fetch 无超时/AbortController**：轮询与请求无取消，网络挂起会一直挂着。
- **`deriveSteps`/`overallProgress` total 与展示节点数不一致**（`src/lib/progress.ts`）：条件路由未执行的节点不出现，进度分母跳变。
- **launch.json `cwd` 指向旧路径 `E:\Finecho\frontend`**（已修复为 `E:\dii\Finecho\frontend`）。
- **`.env.example` ALLOWED_ORIGINS 含遗留 3000、缺 4173**。
- **`graphLayout.ts` level>=4 越界 `radialDistance[level]`→NaN**：后端 max_depth 1–3 挡住，但无前端防御。

## 七、Docker / 部署

- **Dockerfile 不打包前端 dist**：Docker 部署后无页面服务；README 未说明 Docker 用法。
- **wheel 不含 `scripts/` 与 `data/`**：装 wheel 后无数据目录（Dockerfile 手动 COPY data 缓解）。
- **seed 演示数据混入业务库**（`policy_service.py:461-754`，约 290 行）：`_document_id` SHA1 截断 12 位可碰撞。

## 八、环境备注（2026-08-05）

- 机器原本无 python/node；已用 winget 安装 Python 3.11.9（`C:\Users\28630\AppData\Local\Programs\Python\Python311`）与 Node.js 24.19.0（`C:\Program Files\nodejs`）。
- 注意 PATH：`python` 仍指向 WindowsApps 重定向器，需用绝对路径或 venv 内解释器；`node` 新装未进当前 shell PATH。
- 项目根 `.venv` 已创建；`pip install -e ".[dev]"` 进行中。`.env` 已从 `.env.example` 复制。
