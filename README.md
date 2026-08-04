# FinEcho 后端初版

面向突发政策的产业链影响归因与上市公司受益真实性核验服务。项目按原始目录拆分：

```text
agent/  LangGraph 状态、节点、工作流与可选 LLM 解析器
api/    FastAPI 路由、依赖注入、异常处理与 API 中间件
app/    配置、生命周期及应用入口
data/   可替换的演示公司与证据数据
src/    模型、Repository、GraphRAG 与业务服务
tests/  GraphRAG 单测及 HTTP 全链路测试
```

## 快速启动

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

启动后访问 `http://localhost:8000/docs`。未设置 `OPENAI_API_KEY` 时，系统使用确定性规则解析政策，整条 API 链路仍可运行。要启用模型解析：

```bash
pip install -e ".[dev,llm]"
```

## 主要接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health`、`/ready` | 存活/就绪检查 |
| `POST` | `/api/v1/analyses` | 提交政策分析，返回任务 ID |
| `GET` | `/api/v1/analyses/{task_id}` | 查询任务状态和结果 |
| `GET` | `/api/v1/analyses/{task_id}/result` | 只读取完成结果 |
| `GET` | `/api/v1/graphs/{task_id}` | 获取前端图谱的 nodes/edges |
| `GET` | `/api/v1/companies/{id}` | 获取公司基本面样例 |
| `GET` | `/api/v1/companies/{id}/evidence?q=...` | 靶向检索证据 |
| `GET` | `/api/v1/reports/{task_id}.md` | 下载一页式 Markdown 简报 |

提交示例：

```bash
curl -X POST http://localhost:8000/api/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{
    "policy_title": "新型储能示范政策",
    "policy_text": "支持新型储能项目建设，推动储能电池及新能源产业发展。"
  }'
```

## 已实现的 API 中间件

- 请求 ID 与 JSON 结构化访问日志
- 可选 `X-API-Key` 鉴权（`.env` 中配置 `API_KEY` 后开启）
- 基于客户端 IP 的内存限流，并返回限流响应头
- 请求体大小限制、统一参数校验与异常响应
- CORS、安全响应头、处理耗时响应头

## 从演示版升级到生产版

1. 将 `InMemoryJobRepository` 换为 PostgreSQL/Redis，将后台任务换为 Arq/Celery。
2. 在 `GraphRAGService` 后接 ChromaDB 向量召回，并把财报实体关系写入 Neo4j 或图数据库。
3. 将 PDF 入库拆成独立流水线：下载、OCR、MD&A/问询函分段、元数据校验、Embedding。
4. 对财务比例使用结构化财务表计算；LLM 只负责提取候选与解释，不能直接生成数字。
5. API Key 适合黑客松演示；正式环境应接 OAuth2/JWT、可信代理和分布式限流。

## 优化记录

- [01 多 Agent 条件路由与循环回退](docs/optimization-01-langgraph-multi-agent.md)：核验拆分为 form_candidate / gather_evidence / adversarial_check 三个 Agent，匹配与证据两处循环放宽且保证有界终止。
- [02 LLM 对抗式事实核查](docs/optimization-02-llm-adversarial-factcheck.md)：把 LLM 接入对抗式核验，规则分 + LLM 立场加权合成，无 key/依赖缺失/API 故障均安全降级。

> `data/` 中所有公司比例与文本均为演示数据，不构成投资建议，也不能用于真实交易决策。

