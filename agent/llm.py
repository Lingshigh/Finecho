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


class OptionalPolicyLLM:
    """Optional structured LLM adapter; returns None when no provider is configured."""

    def __init__(self, api_key: str, model: str) -> None:
        self._runner = None
        self._fact_check_runner = None
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
