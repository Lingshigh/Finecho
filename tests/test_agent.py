import asyncio
from pathlib import Path

from agent.graph import build_analysis_graph
from agent.llm import OptionalPolicyLLM
from src.services.rag_service import GraphRAGService

DATA_DIR = Path(__file__).parents[1] / "data"


def _make_rag() -> GraphRAGService:
    return GraphRAGService(DATA_DIR)


def _run_graph(rag: GraphRAGService, **overrides: object) -> dict:
    graph = build_analysis_graph(rag, OptionalPolicyLLM(api_key="", model="gpt-4.1-mini"))
    initial: dict[str, object] = {
        "task_id": "test-task",
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


def test_energy_storage_policy_flow() -> None:
    state = _run_graph(_make_rag())
    assert state["policy_keywords"]
    assert state["candidates"]
    assert state["verdicts"]
    assert state["nodes"]
    assert state["edges"]
    names = {item["name"] for item in state["companies"]}
    assert "宁德时代" in names


def test_broaden_match_loop_recovers_no_match_policy() -> None:
    """政策里没有可识别关键词且标题不含中文词时，应走 broaden_match 重试循环而非空跑。"""
    state = _run_graph(
        _make_rag(),
        request={
            "policy_title": "XYZ",
            "policy_text": "鼓励某某新产业健康发展，推动试点示范与应用推广工作。",
            "target_companies": [],
        },
    )
    assert state["verdicts"], "回退循环应至少产出候选公司核验结论"
    assert state["match_attempts"] >= 1
    assert any("放宽" in message for message in state["warnings"])


def test_broaden_evidence_loop_recovers_when_evidence_sparse() -> None:
    """默认证据充足时不触发放宽；候选无证据时应触发 broaden_evidence 循环。"""
    from agent.nodes import route_evidence

    default_state = _run_graph(_make_rag())
    assert default_state["evidence_attempts"] == 0

    # 每家公司都有证据、相关度达阈值 → 直接进入对抗式核验。
    sufficient = {
        "candidates": default_state["candidates"],
        "evidence": default_state["evidence"],
        "evidence_attempts": 0,
        "max_evidence_attempts": 3,
    }
    assert route_evidence(sufficient) == "adversarial_check"

    # 某家候选无任何证据 → 回退到 broaden_evidence 重试。
    sparse_evidence = {
        "candidates": default_state["candidates"],
        "evidence": {cand.company_id: [] for cand in default_state["candidates"]},
        "evidence_attempts": 0,
        "max_evidence_attempts": 3,
    }
    assert route_evidence(sparse_evidence) == "broaden_evidence"

    # 重试耗尽后即使仍无证据也进入对抗式核验，保证有界终止。
    exhausted = {**sparse_evidence, "evidence_attempts": 3}
    assert route_evidence(exhausted) == "adversarial_check"


def test_hotspot_risk_detection() -> None:
    """演示公司 000001.DEMO 主营收入暴露度仅 3%，应被判为热点/蹭概念风险。"""
    state = _run_graph(
        _make_rag(),
        request={
            "policy_title": "新型储能示范政策",
            "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
            "target_companies": ["000001.DEMO"],
        },
    )
    verdicts = {item.company_id: item for item in state["verdicts"]}
    assert "000001.DEMO" in verdicts
    assert verdicts["000001.DEMO"].verdict == "hotspot_risk"


def test_retry_cap_prevents_infinite_loop() -> None:
    state = _run_graph(_make_rag(), max_match_attempts=0)
    assert state["match_attempts"] == 0
    assert state["verdicts"]


def test_rule_score_penalizes_low_exposure() -> None:
    from agent.nodes import rule_score

    hotspot = rule_score(exposure=0.03, rd_ratio=0.009, relevance=0.45, product_overlap=False, has_evidence=True)
    legit = rule_score(exposure=0.89, rd_ratio=0.083, relevance=0.93, product_overlap=True, has_evidence=True)
    assert hotspot < 0.4
    assert legit >= 0.7


def test_blend_scores_llm_challenge_lowers_rule_score() -> None:
    from agent.nodes import blend_scores

    rule = 0.6
    assert blend_scores(rule, "challenge") < rule
    assert blend_scores(rule, "support") > rule
    # neutral 视为证据不足，向 0.5 保守拉低，介于 challenge 与 support 之间。
    assert blend_scores(rule, "challenge") < blend_scores(rule, "neutral") < blend_scores(rule, "support")
    assert blend_scores(rule, None) == rule  # LLM 未配置/失败时纯规则


async def _run_with_stub_llm(stub_llm, **overrides: object) -> dict:
    from agent.nodes import build_nodes

    rag = _make_rag()
    nodes = build_nodes(rag, stub_llm)
    state: dict = {
        "task_id": "stub-task",
        "request": {
            "policy_title": "新型储能示范政策",
            "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
            "target_companies": ["000001.DEMO", "300750.SZ"],
        },
        "warnings": [],
        "match_attempts": 0,
        "evidence_attempts": 0,
        "max_match_attempts": 3,
        "max_evidence_attempts": 3,
        "lenient_matching": False,
    }
    state.update(overrides)
    state.update(await nodes["extract_policy"](state))
    state.update(nodes["expand_chain"](state))
    state.update(nodes["match_companies"](state))
    state.update(nodes["form_candidate"](state))
    state.update(nodes["gather_evidence"](state))
    return await nodes["adversarial_check"](state)


class _StubLLM:
    def __init__(self, stance: str) -> None:
        self.stance = stance

    async def parse(self, *args, **kwargs):
        return None

    async def verify(self, company, policy, claim, evidence):
        from agent.llm import FactCheckResult

        ids = [item.id for item in evidence]
        return FactCheckResult(stance=self.stance, rationale="stub", supporting_evidence_ids=ids)


async def test_adversarial_check_llm_support_raises_score() -> None:
    result = await _run_with_stub_llm(_StubLLM("support"))
    assert result["verdicts"]
    # 幻影科技暴露度极低，即使 LLM 支持也应保持热点风险。
    by_id = {v.company_id: v for v in result["verdicts"]}
    assert by_id["000001.DEMO"].verdict == "hotspot_risk"


async def test_adversarial_check_llm_challenge_lowers_score() -> None:
    from agent.nodes import blend_scores

    result = await _run_with_stub_llm(_StubLLM("challenge"))
    assert result["verdicts"]
    by_id = {v.company_id: v for v in result["verdicts"]}
    # LLM 质疑宁德时代后，其受益概率应被拉低，且 reasoning 中带 LLM 立场说明。
    assert by_id["300750.SZ"].benefit_probability < blend_scores(0.9, None) + 0.05
    assert any("LLM 事实核查" in r for r in by_id["300750.SZ"].reasons)
