from scripts.build_shenzhen_policy import build_documents, parse_items

SAMPLE_HTML = """
<div class="item"><div class="t"><span class="tag-policy">政策</span>
  <a href="https://www.sz.gov.cn/cn/xxgk/zfxxgj/zcfg/content/post_12345.html">深圳市人民政府关于印发《新型储能产业发展行动计划》的通知</a>
  </div><div class="meta">2026-07-01</div></div>
<div class="item"><div class="t"><span class="tag-policy">政策</span>
  <a href="https://www.sz.gov.cn/cn/xxgk/zfxxgj/zcfg/content/post_12346.html">深圳市人民政府办公厅关于促进低空经济高质量发展的若干措施</a>
  </div><div class="meta">2026-06-20</div></div>
"""


def test_parse_items_extracts_triples() -> None:
    items = parse_items(SAMPLE_HTML)
    assert len(items) == 2
    assert items[0][0].startswith("https://www.sz.gov.cn")
    assert "新型储能产业发展行动计划" in items[0][1]
    assert items[0][2] == "2026-07-01"


def test_build_documents_sets_shenzhen_region() -> None:
    items = parse_items(SAMPLE_HTML)
    documents = build_documents(items, "https://www.sz.gov.cn")
    assert len(documents) == 2
    assert all(doc.scope.regions == ["深圳市"] for doc in documents)
    assert documents[0].authority_level.value == "city"


def test_build_documents_infers_industry() -> None:
    items = parse_items(SAMPLE_HTML)
    documents = build_documents(items, "https://www.sz.gov.cn")
    industries = [doc.scope.industries for doc in documents]
    assert any("储能" in inds for inds in industries)
    assert any("低空经济" in inds for inds in industries)
