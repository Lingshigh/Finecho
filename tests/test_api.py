from fastapi.testclient import TestClient

from app.main import app


def test_health_and_analysis_flow() -> None:
    payload = {
        "policy_title": "新型储能示范政策",
        "policy_text": "支持新型储能项目建设，推动储能电池、电池管理系统及新能源产业发展。",
    }
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200

        accepted = client.post("/api/v1/analyses", json=payload)
        assert accepted.status_code == 202
        task_id = accepted.json()["task_id"]

        task = client.get(f"/api/v1/analyses/{task_id}")
        assert task.status_code == 200
        assert task.json()["status"] == "succeeded"

        graph = client.get(f"/api/v1/graphs/{task_id}")
        assert graph.status_code == 200
        assert any(node["type"] == "company" for node in graph.json()["nodes"])

        report = client.get(f"/api/v1/reports/{task_id}.md")
        assert report.status_code == 200
        assert "真实性核验简报" in report.text


def test_validation_error_contract() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analyses", json={"policy_title": "短", "policy_text": "不足"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
