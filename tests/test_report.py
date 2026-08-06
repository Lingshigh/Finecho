import asyncio
from pathlib import Path

from src.models.schemas import AnalysisResult, GraphEdge, GraphNode
from src.services.report_service import build_rule_report

DATA_DIR = Path(__file__).parents[1] / "data"


def _run_graph(**overrides: object) -> dict:
    from agent.graph import build_analysis_graph
    from agent.llm import OptionalPolicyLLM
    from src.services.rag_service import GraphRAGService

    rag = GraphRAGService(DATA_DIR)
    graph = build_analysis_graph(rag, OptionalPolicyLLM(api_key="", model="gpt-4.1-mini"))
    initial: dict[str, object] = {
        "task_id": "report-test",
        "request": {
            "policy_title": "新型储能示范政策",
            "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
            "target_companies": [],
        },
        "warnings": [],
        "match_attempts": 0,
        "evidence_attempts": 0,
        "max_match_attempts": 3,
        "max_evidence_attempts": 3,
        "lenient_matching": False,
    }
    initial.update(overrides)
    return asyncio.run(graph.ainvoke(initial))


def _rule_report(**overrides: object):
    from src.models.schemas import CompanyVerdict

    defaults = {
        "policy_title": "新型储能示范政策",
        "policy_summary": "支持新型储能项目建设。",
        "keywords": ["储能", "电池"],
        "industries": ["储能", "新能源"],
        "products": ["储能电池", "电池管理系统"],
        "nodes": [
            GraphNode(id="industry:储能", label="储能", type="industry", level=1),
            GraphNode(id="chain:储能电池", label="储能电池", type="supply_chain", level=2),
        ],
        "edges": [
            GraphEdge(source="industry:储能", target="chain:储能电池", relation="transmits"),
        ],
        "verdicts": [
            CompanyVerdict(
                company_id="300750.SZ",
                company_name="宁德时代",
                ticker="300750.SZ",
                verdict="high_confidence",
                benefit_probability=0.8,
                divergence_score=0.2,
                revenue_exposure=0.85,
                reasons=["核验通过"],
                evidence=[],
            )
        ],
        "companies": [
            {
                "id": "300750.SZ",
                "name": "宁德时代",
                "ticker": "300750.SZ",
                "financials": {"revenue_2025": 4237.0, "net_profit_2025": 722.0, "rd_expense_2025": 221.5},
                "rd_ratio": 0.052,
                "capacity_constraint": "锂电材料价格波动",
                "revenue_exposure": 0.85,
            },
            {
                "id": "002594.SZ",
                "name": "比亚迪",
                "ticker": "002594.SZ",
                "financials": {"revenue_2025": 8039.6, "net_profit_2025": 326.2, "rd_expense_2025": 579.8},
                "rd_ratio": 0.072,
                "capacity_constraint": "海外市场准入",
                "revenue_exposure": 0.9,
            },
        ],
    }
    defaults.update(overrides)
    return build_rule_report(**defaults)


def test_compose_report_rule_mode_produces_complete_structure() -> None:
    """无 LLM 时完整图跑通：研报由规则模板生成，四维度齐全（也覆盖 LLM 失败降级路径）。"""
    state = _run_graph()
    report = state.get("report")
    assert report is not None
    assert report.generated_by == "rule"
    assert len(report.dimensions) == 4
    keys = {dim.key for dim in report.dimensions}
    assert keys == {"policy_transmission", "competition", "technology", "supply_chain"}
    assert report.role.name
    assert report.executive_summary
    assert report.sources


def test_report_four_dimension_order_fixed() -> None:
    report = _rule_report()
    names = [dim.name for dim in report.dimensions]
    assert names == ["政策影响传导", "市场竞争格局", "技术迭代路径", "供应链风险"]


def test_competition_dimension_ranks_by_revenue() -> None:
    report = _rule_report()
    competition = next(d for d in report.dimensions if d.key == "competition")
    text = "\n".join(competition.key_facts)
    assert "1. 比亚迪" in text  # 营收 8039.6 最高，居首
    assert "2. 宁德时代" in text
    assert "营收" in text


def test_supply_chain_dimension_uses_capacity_constraint() -> None:
    report = _rule_report()
    supply = next(d for d in report.dimensions if d.key == "supply_chain")
    text = "\n".join(supply.key_facts)
    assert "宁德时代" in text
    assert "锂电材料价格波动" in text


def test_hotspot_company_excluded_from_revenue_ranking() -> None:
    from src.models.schemas import CompanyVerdict

    report = _rule_report(
        companies=[
            {
                "id": "000001.DEMO",
                "name": "幻影科技（演示）",
                "ticker": "000001.DEMO",
                "revenue_exposure": 0.03,
                "rd_ratio": 0.009,
                "capacity_constraint": "相关产品规模较小",
            },
            {
                "id": "300750.SZ",
                "name": "宁德时代",
                "ticker": "300750.SZ",
                "financials": {"revenue_2025": 4237.0, "net_profit_2025": 722.0},
                "rd_ratio": 0.052,
                "capacity_constraint": "锂电材料价格波动",
            },
        ],
        verdicts=[
            CompanyVerdict(
                company_id="000001.DEMO",
                company_name="幻影科技（演示）",
                ticker="000001.DEMO",
                verdict="hotspot_risk",
                benefit_probability=0.0,
                divergence_score=0.77,
                revenue_exposure=0.03,
                reasons=["无实质业务"],
                evidence=[],
            )
        ],
    )
    competition = next(d for d in report.dimensions if d.key == "competition")
    assert "幻影科技" not in "\n".join(competition.key_facts)
    supply = next(d for d in report.dimensions if d.key == "supply_chain")
    assert "幻影科技" in "\n".join(supply.key_facts)


def test_frameworks_present_in_rule_mode() -> None:
    report = _rule_report()
    assert report.swot is not None and report.swot.rows
    assert report.porter_five_forces is not None and report.porter_five_forces.rows
    assert report.pest is not None and report.pest.rows
    for table in (report.swot, report.porter_five_forces, report.pest):
        for row in table.rows:
            assert row.level in {"high", "medium", "low"}
            assert row.factor
            assert row.statement


def test_report_never_raises_on_empty_data() -> None:
    report = build_rule_report(policy_title="测试")
    assert report.generated_by == "rule"
    assert len(report.dimensions) == 4
    assert report.swot is not None
    assert report.porter_five_forces is not None
    assert report.pest is not None


def test_report_sources_deduplicated() -> None:
    from src.models.schemas import CompanyVerdict, Evidence

    evidence = [
        Evidence(id="e1", company_id="300750.SZ", source_type="annual_report",
                 title="年报", excerpt="", source_url="https://example.com/a", relevance=0.5),
        Evidence(id="e2", company_id="300750.SZ", source_type="annual_report",
                 title="年报2", excerpt="", source_url="https://example.com/a", relevance=0.4),
    ]
    report = _rule_report(
        verdicts=[
            CompanyVerdict(
                company_id="300750.SZ", company_name="宁德时代", ticker="300750.SZ",
                verdict="high_confidence", benefit_probability=0.8,
                divergence_score=0.2, revenue_exposure=0.85,
                reasons=["x"], evidence=evidence,
            )
        ]
    )
    urls = [source.url for source in report.sources if source.url]
    assert len(urls) == len(set(urls))


def test_analysis_result_serializes_report() -> None:
    report = _rule_report()
    result = AnalysisResult(
        task_id="t1", policy_summary="s", policy_keywords=["k"],
        nodes=[], edges=[], verdicts=[], report=report,
    )
    payload = result.model_dump(mode="json")
    assert payload["report"]["generated_by"] == "rule"
    assert len(payload["report"]["dimensions"]) == 4
    # report 为 None 时可序列化。
    empty = AnalysisResult(task_id="t2", policy_summary="s", policy_keywords=[], nodes=[], edges=[], verdicts=[])
    assert empty.model_dump(mode="json")["report"] is None
