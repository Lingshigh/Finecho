import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PolicyExtraction(BaseModel):
    summary: str = Field(max_length=300)
    keywords: list[str] = Field(max_length=12)
    industries: list[str] = Field(max_length=10)
    supply_chain_nodes: list[str] = Field(max_length=15)


class FactCheckResult(BaseModel):
    """对抗式事实核查输出：对候选结论的支持/质疑 + 引用的证据 id。"""

    stance: Literal["support", "challenge", "neutral"]
    rationale: str = Field(max_length=500)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class ReportRequest(BaseModel):
    """产业研报结构化输出（LLM 分支）。字段与 IndustryReport 对齐，由生成侧回填元信息。"""

    role_name: str
    role_perspective: str
    executive_summary: str = Field(max_length=300)
    policy_transmission: str
    policy_transmission_facts: list[str] = Field(default_factory=list, max_length=5)
    competition: str
    competition_facts: list[str] = Field(default_factory=list, max_length=5)
    technology: str
    technology_facts: list[str] = Field(default_factory=list, max_length=5)
    supply_chain: str
    supply_chain_facts: list[str] = Field(default_factory=list, max_length=5)
    swot: list[dict] = Field(default_factory=list, max_length=8)
    porter_five_forces: list[dict] = Field(default_factory=list, max_length=6)
    pest: list[dict] = Field(default_factory=list, max_length=4)
    sources: list[str] = Field(default_factory=list, max_length=20)


class OptionalPolicyLLM:
    """Optional structured LLM adapter; returns None when no provider is configured."""

    def __init__(self, api_key: str, model: str) -> None:
        self._runner = None
        self._fact_check_runner = None
        self._report_runner = None
        self._report_model = ""
        if not api_key:
            return
        try:
            from langchain_openai import ChatOpenAI

            prompt = (
                "你是金融产业链研究员。仅根据给定政策提取摘要、政策关键词、"
                "一级受影响行业和二级供应链节点。不要编造公司、财务数字或政策事实。\n\n"
                "政策标题：{title}\n政策正文：{text}"
            )
            self._runner = ChatOpenAI(
                model=model, api_key=api_key, temperature=0
            ).with_structured_output(PolicyExtraction)
            self._prompt = prompt

            fact_check_prompt = (
                "你是金融事实核查员。给定一家公司、一段政策、公司披露的财务证据与一个候选结论，"
                "请判断该结论是否成立。必须仅依据提供的证据，不得引入外部信息或编造数字。\n\n"
                "公司：{company_name}\n"
                "政策：{policy}\n"
                "候选结论：{claim}\n"
                "证据列表：\n{evidence_text}\n\n"
                "请输出：\n"
                "- stance：support（支持）、challenge（质疑，证据不支持结论或存在矛盾）、neutral（证据不足，无法判断）\n"
                "- rationale：一句简明理由\n"
                "- supporting_evidence_ids：支持你判断的证据 id 列表"
            )
            self._fact_check_prompt = fact_check_prompt
            self._fact_check_runner = ChatOpenAI(
                model=model, api_key=api_key, temperature=0
            ).with_structured_output(FactCheckResult)

            report_prompt = (
                "你是资深产业研究分析师（麦肯锡/投行研究风格）。基于以下已核验的数据生成专业产业研究报告。\n"
                "政策标题：{policy_title}\n政策摘要：{summary}\n政策关键词：{keywords}\n"
                "产业链：行业={industries}；供应链节点={products}\n"
                "图谱关系统计：{edge_stats}\n"
                "公司核验与财务证据：\n{company_block}\n\n"
                "要求：\n"
                "1. 四维度全覆盖：政策影响传导、市场竞争格局、技术迭代路径、供应链风险。\n"
                "2. 每个维度的 facts 必须仅基于上述数据，不得编造数字；每条 fact 可标注来源（来源：2025年年度报告/来源：公司财务数据）。\n"
                "3. role_name 用分析师角色名，role_perspective 用一句麦肯锡/投行口吻概括分析视角。\n"
                "4. executive_summary 不超过 180 字，先给结论再给依据。\n"
                "5. swot/porter_five_forces/pest 均为 [{factor, level, statement}] 结构，level 用 high/medium/low。\n"
                "6. sources 汇总所有用到的来源链接与数据来源（去重）。"
            )
            self._report_prompt = report_prompt
            self._report_runner = ChatOpenAI(
                model=model, api_key=api_key, temperature=0
            ).with_structured_output(ReportRequest)
            self._report_model = model
        except ImportError:
            logger.warning("OPENAI_API_KEY 已配置，但未安装 llm 可选依赖")

    async def parse(self, title: str, text: str) -> PolicyExtraction | None:
        if self._runner is None:
            return None
        try:
            return await self._runner.ainvoke(self._prompt.format(title=title, text=text))
        except Exception:
            logger.exception("LLM policy extraction failed; using deterministic fallback")
            return None

    async def verify(self, company: dict, policy: str, claim: str, evidence: list) -> FactCheckResult | None:
        """对候选核验结论做对抗式事实核查；未配置 LLM 或调用失败时返回 None，走规则 fallback。"""
        if self._fact_check_runner is None:
            return None
        if not evidence:
            return None
        evidence_text = "\n".join(
            f"- [{item.id}] ({item.source_type}) {item.title}：{item.excerpt}" for item in evidence
        )
        try:
            return await self._fact_check_runner.ainvoke(
                self._fact_check_prompt.format(
                    company_name=company["name"],
                    policy=policy,
                    claim=claim,
                    evidence_text=evidence_text,
                )
            )
        except Exception:
            logger.exception("LLM fact check failed; using rule-based fallback")
            return None

    async def generate_industry_report(
        self,
        *,
        policy_title: str,
        summary: str,
        keywords: list[str],
        industries: list[str],
        products: list[str],
        edge_stats: str,
        companies: list[dict],
        verdicts: list,
        related_policies: list | None = None,
        timeout_seconds: float = 30,
    ):
        """生成专业产业研报；未配置 LLM 或调用失败/超时时返回 None，走规则模板兜底。

        入参已由调用方预折叠为紧凑文本（companies 转简表、verdicts 取关键字段），
        避免把完整分析结果塞进 prompt。
        """
        if self._report_runner is None:
            return None
        company_block = "\n".join(
            f"- {c.get('name', '')}（{c.get('ticker', '')}）营收 "
            f"{c.get('financials', {}).get('revenue_2025', 'N/A')} 亿元，"
            f"研发费用率 {c.get('rd_ratio', 'N/A')}，约束：{c.get('capacity_constraint', 'N/A')}"
            for c in companies
        )
        verdict_lines = []
        for verdict in verdicts:
            evidence_urls = [
                item.source_url for item in verdict.evidence if item.source_url
            ]
            verdict_lines.append(
                f"- {verdict.company_name}（{verdict.ticker}）判定 {verdict.verdict}，"
                f"受益概率 {verdict.benefit_probability:.2f}，背离度 {verdict.divergence_score:.2f}，"
                f"证据来源：{'、'.join(evidence_urls[:2]) or '无'}"
            )
        if verdict_lines:
            company_block += "\n核验结论：\n" + "\n".join(verdict_lines)
        if related_policies:
            policy_lines = [
                f"- {item.title}（来源：{item.source_url or '政策库'}）"
                for item in related_policies[:6]
            ]
            company_block += "\n政策库关联政策：\n" + "\n".join(policy_lines)
        try:
            raw = await asyncio.wait_for(
                self._report_runner.ainvoke(
                    self._report_prompt.format(
                        policy_title=policy_title,
                        summary=summary,
                        keywords="、".join(keywords),
                        industries="、".join(industries),
                        products="、".join(products),
                        edge_stats=edge_stats,
                        company_block=company_block,
                    )
                ),
                timeout_seconds,
            )
        except Exception:
            logger.exception("LLM report generation failed; using rule template")
            return None

        # 结构校验：LLM 可能少输出某些维度/字段，缺失时由调用方用规则模板补位。
        from src.models.schemas import IndustryReport

        dimension_map = {
            "policy_transmission": ("政策影响传导", raw.policy_transmission, raw.policy_transmission_facts),
            "competition": ("市场竞争格局", raw.competition, raw.competition_facts),
            "technology": ("技术迭代路径", raw.technology, raw.technology_facts),
            "supply_chain": ("供应链风险", raw.supply_chain, raw.supply_chain_facts),
        }

        def _to_framework(rows: list[dict], name: str):
            from src.models.schemas import ReportFrameworkRow, ReportFrameworkTable

            if not rows:
                return None
            valid = [
                ReportFrameworkRow(
                    factor=str(item.get("factor", "")),
                    level=item.get("level", "medium"),
                    statement=str(item.get("statement", "")),
                )
                for item in rows
                if isinstance(item, dict) and item.get("factor")
            ]
            return ReportFrameworkTable(name=name, rows=valid) if valid else None

        from src.models.schemas import (
            ReportDimension,
            ReportRole,
            ReportSource,
        )

        dimensions: list[ReportDimension] = []
        for key, (name, summary_text, facts) in dimension_map.items():
            if summary_text.strip():
                dimensions.append(
                    ReportDimension(
                        name=name,
                        key=key,
                        summary=summary_text,
                        key_facts=[str(item) for item in facts if item],
                        sources=[],
                    )
                )
        sources = [
            ReportSource(label="政策原文与公司披露", url=url)
            for url in raw.sources
            if isinstance(url, str) and url.startswith("http")
        ]
        return IndustryReport(
            generated_by="llm",
            role=ReportRole(name=raw.role_name, perspective=raw.role_perspective),
            executive_summary=raw.executive_summary,
            dimensions=dimensions,
            swot=_to_framework(raw.swot, "SWOT"),
            porter_five_forces=_to_framework(raw.porter_five_forces, "波特五力"),
            pest=_to_framework(raw.pest, "PEST"),
            sources=sources,
            model_name=self._report_model,
        )
