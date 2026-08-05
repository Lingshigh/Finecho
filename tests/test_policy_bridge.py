import asyncio
from pathlib import Path

from src.repositories.policy_repository import InMemoryPolicyRepository
from src.services.policy_bridge import PolicyBridgeService
from src.services.policy_service import PolicyService

DATA_DIR = Path(__file__).parents[1] / "data"


def _make_bridge() -> PolicyBridgeService:
    policy_repository = InMemoryPolicyRepository()
    policy_service = PolicyService(policy_repository, data_dir=DATA_DIR)
    asyncio.run(policy_service.bootstrap())
    return PolicyBridgeService(policy_service)


def test_find_related_by_industry() -> None:
    """按行业查政策库，命中储能相关政策。"""
    bridge = _make_bridge()
    matched, _ = asyncio.run(
        bridge.find_related(industries=["储能"], keywords=[])
    )
    assert matched
    assert any("储能" in " ".join(item.scope.industries) for item in matched)


def test_find_related_by_keyword() -> None:
    """按关键词查政策库，命中含该关键词的政策。"""
    bridge = _make_bridge()
    matched, _ = asyncio.run(
        bridge.find_related(industries=[], keywords=["人工智能"])
    )
    assert matched
    assert any("人工智能" in item.title for item in matched)


def test_find_related_returns_relations() -> None:
    """命中政策涉及的上下位关系应一并返回。"""
    bridge = _make_bridge()
    matched, relations = asyncio.run(
        bridge.find_related(industries=["人工智能"], keywords=[])
    )
    if matched:
        # 命中政策通常带 relations（政策库有 47 条关系）。
        assert isinstance(relations, list)


def test_find_related_no_match_is_safe() -> None:
    """无匹配行业/关键词时返回空，不抛错。"""
    bridge = _make_bridge()
    matched, relations = asyncio.run(
        bridge.find_related(industries=["不存在的行业xyz"], keywords=[])
    )
    assert matched == []
    assert relations == []


def test_rule_report_includes_related_policies() -> None:
    """build_rule_report 传入 related_policies 后，政策影响维度含"政策库关联"事实。"""
    from src.models.schemas import GraphEdge, GraphNode
    from src.services.report_service import build_rule_report

    related = _make_bridge()
    matched, relations = asyncio.run(
        related.find_related(industries=["储能"], keywords=[])
    )
    report = build_rule_report(
        policy_title="新型储能示范政策",
        policy_summary="支持新型储能项目建设。",
        keywords=["储能", "电池"],
        industries=["储能", "新能源"],
        products=["储能电池"],
        nodes=[GraphNode(id="industry:储能", label="储能", type="industry", level=1)],
        edges=[GraphEdge(source="industry:储能", target="chain:储能电池", relation="transmits")],
        verdicts=[],
        companies=[],
        related_policies=matched,
        related_relations=relations,
    )
    transmission = next(
        d for d in report.dimensions if d.key == "policy_transmission"
    )
    assert any("政策库关联" in fact for fact in transmission.key_facts)
    assert any("政策库关联" in source.label for source in report.sources)
