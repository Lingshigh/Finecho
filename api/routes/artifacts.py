from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from api.dependencies import AnalysisServiceDep
from src.core.exceptions import ConflictError
from src.models.schemas import GraphEdge, GraphNode, TaskStatus
from src.services.analysis_service import AnalysisService

router = APIRouter(tags=["artifacts"])


async def _completed_result(task_id: str, service: AnalysisService):
    task = await service.get(task_id)
    if task.status is not TaskStatus.SUCCEEDED or task.result is None:
        raise ConflictError(
            "分析任务尚未完成", details={"task_id": task_id, "status": task.status.value}
        )
    return task.result


@router.get("/graphs/{task_id}")
async def get_graph(
    task_id: str, service: AnalysisServiceDep
) -> dict[str, list[GraphNode] | list[GraphEdge]]:
    result = await _completed_result(task_id, service)
    return {"nodes": result.nodes, "edges": result.edges}


@router.get("/reports/{task_id}.md", response_class=PlainTextResponse)
async def download_report(task_id: str, service: AnalysisServiceDep) -> PlainTextResponse:
    result = await _completed_result(task_id, service)
    rows = [
        "# FinEcho 政策影响与真实性核验简报",
        "",
        f"生成时间：{result.generated_at.isoformat()}",
        "",
        "## 政策摘要",
        "",
        result.policy_summary,
        "",
        f"关键词：{'、'.join(result.policy_keywords)}",
        "",
        "## 公司核验结论",
        "",
        "| 公司 | 代码 | 结论 | 受益概率 | 背离度 |",
        "|---|---|---:|---:|---:|",
    ]
    for verdict in result.verdicts:
        rows.append(
            f"| {verdict.company_name} | {verdict.ticker} | {verdict.verdict} | "
            f"{verdict.benefit_probability:.1%} | {verdict.divergence_score:.1%} |"
        )
    rows.extend(_report_sections(result.report))
    rows.extend(["", "## 风险提示", ""])
    rows.extend(f"- {warning}" for warning in result.warnings)
    body = "\n".join(rows) + "\n"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="finecho-{task_id}.md"'},
    )


def _report_sections(report) -> list[str]:
    """把产业研报折叠成 Markdown 章节；report 为 None 时返回空列表。"""
    if report is None:
        return []
    from src.models.schemas import IndustryReport

    if not isinstance(report, IndustryReport):
        return []
    rows: list[str] = ["", "## 产业研究报告", ""]
    rows.append(f"**分析视角**：{report.role.name} — {report.role.perspective}")
    rows.append("")
    rows.append(f"生成方式：{'LLM' if report.generated_by == 'llm' else '规则模板'}")
    rows.extend(["", "### 执行摘要", "", report.executive_summary])
    for dimension in report.dimensions:
        rows.extend(["", f"### {dimension.name}", "", dimension.summary])
        if dimension.key_facts:
            rows.extend([f"- {fact}" for fact in dimension.key_facts])
    for table in (
        report.swot,
        report.porter_five_forces,
        report.pest,
    ):
        if table is None:
            continue
        rows.extend(["", f"### {table.name}", ""])
        rows.append("| 维度 | 强度 | 说明 |")
        rows.append("|---|---|---|")
        for row in table.rows:
            rows.append(f"| {row.factor} | {row.level} | {row.statement} |")
    if report.sources:
        rows.extend(["", "### 数据来源", ""])
        rows.extend(f"- {source.label}：{source.url or '（本地数据）'}" for source in report.sources)
    return rows
