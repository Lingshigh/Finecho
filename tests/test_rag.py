from pathlib import Path

from src.services.rag_service import GraphRAGService


def test_graph_rag_matches_real_exposure_company() -> None:
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    companies = rag.find_companies(["储能"], ["储能电池"])

    assert companies
    assert companies[0]["name"] == "宁德时代"
    assert rag.retrieve(companies[0]["id"], "储能电池政策研发投入")


def test_graph_contains_company_product_relations() -> None:
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    assert rag.graph.has_node("300750.SZ")
    assert rag.graph.has_edge("300750.SZ", "product:储能电池")
