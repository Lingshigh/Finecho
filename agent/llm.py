import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PolicyExtraction(BaseModel):
    summary: str = Field(max_length=300)
    keywords: list[str] = Field(max_length=12)
    industries: list[str] = Field(max_length=10)
    supply_chain_nodes: list[str] = Field(max_length=15)


class OptionalPolicyLLM:
    """Optional structured LLM adapter; returns None when no provider is configured."""

    def __init__(self, api_key: str, model: str) -> None:
        self._runner = None
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
