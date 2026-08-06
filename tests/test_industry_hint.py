from pathlib import Path

DATA_DIR = Path(__file__).parents[1] / "data"


def _expand_chain(request: dict) -> dict:
    from agent.llm import OptionalPolicyLLM
    from agent.nodes import build_nodes
    from src.services.rag_service import GraphRAGService

    rag = GraphRAGService(DATA_DIR)
    nodes = build_nodes(rag, OptionalPolicyLLM(api_key="", model="gpt-4.1-mini"))
    state = {"request": request, "policy_keywords": [], "warnings": []}
    state.update(__import__("asyncio").run(nodes["extract_policy"](state)))
    return nodes["expand_chain"](state)


def test_industry_hint_placed_first() -> None:
    """显式行业提示应置于 industries 首位，优先级高于规则匹配。"""
    result = _expand_chain({
        "policy_title": "半导体产业扶持政策",
        "policy_text": "支持集成电路、芯片制造与封测产业发展。",
        "target_companies": [],
        "industry_hint": "半导体",
    })
    assert result["industries"][0] == "半导体"


def test_industry_hint_none_matches_current_behavior() -> None:
    """industry_hint 为 None/缺省时，行为与现状完全一致（储能政策识别出储能行业）。"""
    with_hint = _expand_chain({
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
        "target_companies": [],
        "industry_hint": None,
    })
    without_hint = _expand_chain({
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
        "target_companies": [],
    })
    assert with_hint["industries"] == without_hint["industries"]
    assert "储能" in with_hint["industries"]


def test_industry_hint_is_unique() -> None:
    """提示行业重复出现时去重，不产生重复条目。"""
    result = _expand_chain({
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
        "target_companies": [],
        "industry_hint": "储能",
    })
    assert result["industries"].count("储能") == 1
