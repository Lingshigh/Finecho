from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src.models.policy_schemas import (
    AuthorityLevel,
    EvidenceQuote,
    PolicyDocument,
    PolicyImpact,
    PolicyScope,
)
from src.services.policy_agents import (
    DocumentAgentOutput,
    ImpactAgentOutput,
    PolicyAgentOrchestrator,
    RelationAgentOutput,
    RelationProposal,
    ScopeAgentOutput,
)


class StubAgentLLM:
    configured = True

    async def understand_document(self, document: PolicyDocument):
        return DocumentAgentOutput(
            document_number="模型编造〔2026〕99号",
            summary="结构化政策摘要",
            confidence=0.9,
        )

    async def extract_scope(self, document: PolicyDocument):
        return ScopeAgentOutput(
            scope=PolicyScope(
                regions=["火星市"],
                evidence=[EvidenceQuote(excerpt="正文中不存在的适用范围")],
                confidence=0.99,
            )
        )

    async def analyze_impacts(self, document: PolicyDocument):
        return ImpactAgentOutput(
            impacts=[
                PolicyImpact(
                    id="invalid-impact",
                    title="无证据影响",
                    action="补贴",
                    target="企业",
                    summary="模型生成但正文不存在",
                    evidence=[EvidenceQuote(excerpt="正文中不存在的补贴条款")],
                    confidence=0.99,
                )
            ]
        )

    async def reason_relations(self, document, candidates):
        return RelationAgentOutput(
            relations=[
                RelationProposal(
                    target_id="not-in-candidates",
                    relation="based_on",
                    evidence_excerpt="正文中不存在的依据",
                    confidence=0.99,
                )
            ]
        )


def _document() -> PolicyDocument:
    return PolicyDocument(
        id="policy-agent-test",
        title="关于支持储能企业发展的通知",
        issuing_authorities=["测试部门"],
        authority_level=AuthorityLevel.CITY,
        publish_date=date(2026, 8, 5),
        source_name="测试来源",
        content=(
            "测试部门〔2026〕8号\n"
            "第一条 本政策适用于深圳市依法登记的储能企业。\n"
            "第二条 鼓励符合条件的企业申报示范项目。"
        ),
    )


@pytest.mark.asyncio
async def test_agent_pipeline_rejects_unsupported_model_evidence() -> None:
    document, relations = await PolicyAgentOrchestrator(StubAgentLLM()).analyze(_document())

    assert document.document_number == "测试部门〔2026〕8号"
    assert document.scope.regions == ["深圳市"]
    assert document.impacts[0].evidence[0].excerpt in document.content
    assert relations == []
    assert len(document.agent_runs) == 4
    assert any(run.warnings for run in document.agent_runs)


def test_policy_agent_status_and_full_document_import() -> None:
    with TestClient(app) as client:
        status = client.get("/api/v1/policy-agents/status")
        assert status.status_code == 200
        assert status.json()["agents"] == [
            "document_understanding",
            "scope_extraction",
            "impact_analysis",
            "relation_reasoning",
        ]

        response = client.post(
            "/api/v1/policy-imports/document",
            json={
                "title": "关于支持储能企业发展的通知",
                "content": (
                    "测试部门〔2026〕8号\n"
                    "第一条 本政策适用于深圳市依法登记的储能企业。\n"
                    "第二条 鼓励符合条件的企业申报示范项目。"
                ),
                "source_name": "测试政府网站",
                "authority_name": "测试部门",
                "default_authority_level": "city",
                "persist": False,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["persisted"] is False
        assert body["document"]["document_number"] == "测试部门〔2026〕8号"
        assert len(body["document"]["agent_runs"]) == 4
        assert body["document"]["scope"]["regions"] == ["深圳市"]
