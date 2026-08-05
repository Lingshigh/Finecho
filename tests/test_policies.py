from fastapi.testclient import TestClient

from app.main import app


def test_policy_catalog_filters_and_lineage() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/policies", params={"industry": "人工智能"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 2
        assert body["facets"]["authority_levels"]["state_council"] >= 1

        policy_id = "policy-ai-telecom"
        detail = client.get(f"/api/v1/policies/{policy_id}")
        assert detail.status_code == 200
        assert detail.json()["scope"]["industries"] == ["人工智能"]

        lineage = client.get(f"/api/v1/policies/{policy_id}/lineage")
        assert lineage.status_code == 200
        node_ids = {item["id"] for item in lineage.json()["nodes"]}
        assert "policy-ai-plus-state" in node_ids
        assert any(edge["relation"] == "implements" for edge in lineage.json()["edges"])


def test_html_import_quarantines_news_and_keeps_formal_policy() -> None:
    html = """
    <div class="item"><div class="t"><span>政策</span>
      <a href="https://example.gov.cn/policy/1">关于印发《新型储能实施方案》的通知</a>
      </div><div class="meta">2026-08-05</div></div>
    <div class="item"><div class="t"><span>政策</span>
      <a href="https://example.gov.cn/news/2">某部门召开专题学习会议</a>
      </div><div class="meta">2026-08-04</div></div>
    <div class="item"><div class="t"><span>政策</span>
      <a href="https://example.gov.cn/policy/3">《残疾人运输保障办法》...</a>
      </div><div class="meta">2026-08-01</div></div>
    """
    payload = {
        "source_name": "测试政策栏目",
        "authority_name": "测试部委",
        "html": html,
        "default_authority_level": "ministry",
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/policy-imports/html", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["imported"] == 1
        assert body["quarantined"] == 2
        assert body["documents"][0]["scope"]["industries"] == ["储能"]
        assert body["documents"][0]["authenticity_grade"] == "B"


def test_catalog_policy_can_start_existing_analysis_flow() -> None:
    with TestClient(app) as client:
        accepted = client.post("/api/v1/policies/policy-power-system/analyses")
        assert accepted.status_code == 202
        task_id = accepted.json()["task_id"]
        task = client.get(f"/api/v1/analyses/{task_id}")
        assert task.status_code == 200
        assert task.json()["status"] == "succeeded"
        assert task.json()["request"]["policy_title"].startswith("国家发展改革委")


def test_unknown_policy_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/policies/not-found")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
