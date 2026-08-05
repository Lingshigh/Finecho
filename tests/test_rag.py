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


def test_find_companies_uses_graph_traversal() -> None:
    """查询词应通过 BFS 图遍历召回关联公司，而非字符串 overlap。"""
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    # 光伏政策应经图路径 industry:光伏 → 通威/隆基，而不是宁德时代排第一。
    pv = rag.find_companies(["光伏"], ["高纯晶硅", "光伏组件"])
    names = [company["name"] for company in pv]
    assert "通威股份" in names[:3]
    assert "隆基绿能" in names[:3]
    # 检索结果按图距离 + 暴露度排序，且不包含无光伏关联的演示公司。
    assert "幻影科技（演示）" not in names


def test_find_companies_graph_distance_ranks_near_first() -> None:
    """图距离越近排序越靠前：industry 直达公司（dist=1）应排在经产品中转（dist=2）之前。"""
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    # 宁德时代 industry 含"储能"与"新能源"，储能查询应 dist=1 直达。
    companies = rag.find_companies(["储能"], [])
    assert companies and companies[0]["id"] == "300750.SZ"


def test_retrieve_uses_tfidf_cosine() -> None:
    """retrieve 用 TF-IDF 绝对余弦排序，最相关证据应排最前且相关度落在 (0,1]。"""
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    evidence = rag.retrieve("300750.SZ", "储能电池 研发投入 出货规模")
    assert evidence
    assert 0 < evidence[0].relevance <= 1  # 绝对余弦，不做 min-max 归一化
    assert all(0 <= item.relevance <= 1 for item in evidence)


def test_retrieve_empty_when_no_match() -> None:
    """无匹配关键词时应返回空列表，而不是虚构相关度。"""
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    evidence = rag.retrieve("000001.DEMO", "量子计算 脑机接口 元宇宙")
    assert evidence == []


def test_retrieve_raw_cosine_not_normalized() -> None:
    """证据相关度是绝对 TF-IDF 余弦，不做 min-max 归一化（避免跨公司判别力被抹平）。"""
    rag = GraphRAGService(Path(__file__).parents[1] / "data")
    query = "储能电池 研发投入 出货规模"
    evidence = rag.retrieve("300750.SZ", query)
    assert evidence
    top = evidence[0]
    # 与手工 _cosine 一致：非归一化后 top 不应恒为 1.0。
    assert top.relevance < 1.0
    query_vec = rag._vectorize(query)
    doc_vec = rag._doc_vectors[top.id]
    assert abs(top.relevance - rag._cosine(query_vec, doc_vec)) < 1e-3


def _write_dynamic_data(tmp_path: Path, companies: list[dict]) -> Path:
    """在临时目录写入最小 companies.json + companies.dynamic.json。"""
    (tmp_path / "companies.json").write_text("[]", encoding="utf-8")
    (tmp_path / "companies.dynamic.json").write_text(
        __import__("json").dumps(companies, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_load_optional_dynamic_companies(tmp_path: Path) -> None:
    """companies.dynamic.json 存在时被增量加载进公司池。"""
    data = _write_dynamic_data(tmp_path, [
        {
            "id": "688981.SH",
            "ticker": "688981.SH",
            "name": "中芯国际",
            "industries": ["半导体", "电子"],
            "products": ["晶圆制造"],
            "revenue_exposure": 0.6,
            "rd_ratio": 0.12,
            "capacity_constraint": "设备依赖进口",
            "source": "akshare",
        }
    ])
    rag = GraphRAGService(data)
    assert any(c["name"] == "中芯国际" for c in rag.companies)
    # 半导体查询应能经图召回动态公司。
    hits = rag.find_companies(["半导体"], ["晶圆制造"])
    assert hits
    assert hits[0]["name"] == "中芯国际"
    assert rag.graph.has_node("688981.SH")


def test_load_optional_missing_file(tmp_path: Path) -> None:
    """companies.dynamic.json 缺失时静默跳过，不抛错。"""
    data = _write_dynamic_data(tmp_path, [])
    (data / "companies.dynamic.json").unlink()
    rag = GraphRAGService(data)
    assert rag.companies == []

