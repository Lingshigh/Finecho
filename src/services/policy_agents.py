import asyncio
import re
from collections.abc import Sequence
from time import perf_counter
from typing import ClassVar, Literal, Protocol

from pydantic import BaseModel, Field

from src.models.policy_schemas import (
    AuthorityLevel,
    EvidenceQuote,
    PolicyAgentName,
    PolicyAgentRun,
    PolicyAgentStatus,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentType,
    PolicyImpact,
    PolicyLifecycleStatus,
    PolicyRelation,
    PolicyScope,
)

_DOCUMENT_NUMBER_RE = re.compile(
    r"[\u4e00-\u9fff]{1,14}(?:发|办|规|函|令|公告)?[〔\[]20\d{2}[〕\]]\d+号"
)
_CLAUSE_HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百零\d]+[章节条]|[一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）)"
)
_REGION_RE = re.compile(r"[\u4e00-\u9fff]{2,8}(?:省|自治区|市|县|区)")
_REGION_CONTEXT_RE = re.compile(
    r"(?:适用于|适用范围为|位于|在)([\u4e00-\u9fff]{2,8}(?:省|自治区|市|县|区))"
)
_DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
_IMPACT_TERMS: tuple[tuple[str, str, str], ...] = (
    ("支持", "support", "政策支持"),
    ("鼓励", "support", "鼓励发展"),
    ("补贴", "support", "资金补贴"),
    ("奖励", "support", "奖励扶持"),
    ("限制", "restrict", "限制约束"),
    ("禁止", "restrict", "禁止性要求"),
    ("不得", "mandatory", "合规义务"),
    ("应当", "mandatory", "法定义务"),
    ("必须", "mandatory", "强制要求"),
    ("申报", "neutral", "申报要求"),
    ("准入", "restrict", "准入条件"),
)


class DocumentAgentOutput(BaseModel):
    is_formal_policy: bool = True
    document_number: str | None = None
    issuing_authorities: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = AuthorityLevel.UNKNOWN
    document_type: PolicyDocumentType = PolicyDocumentType.OTHER
    lifecycle_status: PolicyLifecycleStatus = PolicyLifecycleStatus.UNKNOWN
    is_red_head: bool | None = None
    summary: str = ""
    clauses: list[PolicyClause] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)


class ScopeAgentOutput(BaseModel):
    scope: PolicyScope


class ImpactAgentOutput(BaseModel):
    impacts: list[PolicyImpact] = Field(default_factory=list)


class RelationProposal(BaseModel):
    target_id: str
    relation: Literal[
        "based_on", "implements", "localizes", "interprets", "cites",
        "supersedes", "repeals", "overlaps", "conflicts_with"
    ]
    evidence_excerpt: str
    confidence: float = Field(default=0.0, ge=0, le=1)


class RelationAgentOutput(BaseModel):
    relations: list[RelationProposal] = Field(default_factory=list)


class PolicyAgentLLM(Protocol):
    configured: bool

    async def understand_document(self, document: PolicyDocument) -> DocumentAgentOutput | None: ...
    async def extract_scope(self, document: PolicyDocument) -> ScopeAgentOutput | None: ...
    async def analyze_impacts(self, document: PolicyDocument) -> ImpactAgentOutput | None: ...
    async def reason_relations(
        self, document: PolicyDocument, candidates: Sequence[PolicyDocument]
    ) -> RelationAgentOutput | None: ...


class OptionalPolicyAgentLLM:
    """Optional structured-output LLM. Every failure is converted to a rule fallback."""

    def __init__(self, api_key: str | None, model: str, timeout_seconds: float = 30) -> None:
        self.configured = False
        self.timeout_seconds = timeout_seconds
        self._runners: dict[str, object] = {}
        if not api_key:
            return
        try:
            from langchain_openai import ChatOpenAI

            client = ChatOpenAI(api_key=api_key, model=model, temperature=0)
            self._runners = {
                "document": client.with_structured_output(DocumentAgentOutput),
                "scope": client.with_structured_output(ScopeAgentOutput),
                "impact": client.with_structured_output(ImpactAgentOutput),
                "relation": client.with_structured_output(RelationAgentOutput),
            }
            self.configured = True
        except Exception:  # noqa: BLE001 - optional dependency must degrade safely
            self._runners = {}

    async def _invoke(self, name: str, prompt: str):
        runner = self._runners.get(name)
        if runner is None:
            return None
        try:
            return await asyncio.wait_for(runner.ainvoke(prompt), self.timeout_seconds)
        except Exception:  # noqa: BLE001 - external model failures must not break imports
            return None

    async def understand_document(self, document: PolicyDocument) -> DocumentAgentOutput | None:
        return await self._invoke("document", _prompt("政策文档识别", document))

    async def extract_scope(self, document: PolicyDocument) -> ScopeAgentOutput | None:
        return await self._invoke("scope", _prompt("适用范围提取", document))

    async def analyze_impacts(self, document: PolicyDocument) -> ImpactAgentOutput | None:
        return await self._invoke("impact", _prompt("政策影响分析", document))

    async def reason_relations(
        self, document: PolicyDocument, candidates: Sequence[PolicyDocument]
    ) -> RelationAgentOutput | None:
        catalog = "\n".join(
            f"- id={item.id}; 标题={item.title}; 文号={item.document_number or '无'}"
            for item in candidates[:80]
            if item.id != document.id
        )
        return await self._invoke(
            "relation", _prompt("政策关系推理", document, f"候选政策目录：\n{catalog}")
        )


def _prompt(task: str, document: PolicyDocument, extra: str = "") -> str:
    return f"""你是{task} Agent。只依据给定正文输出结构化结果，不得补写事实。
所有 evidence/excerpt 必须逐字来自正文；不能确认的字段使用空值或 unknown。
正文：
{document.content[:120000]}
标题：{document.title}
来源：{document.source_name}
{extra}
"""


class PolicyAgentOrchestrator:
    AGENTS: ClassVar[list[PolicyAgentName]] = list(PolicyAgentName)

    def __init__(self, llm: PolicyAgentLLM | None = None, enabled: bool = True) -> None:
        self.llm = llm
        self.enabled = enabled

    def status(self) -> PolicyAgentStatus:
        configured = bool(self.llm and self.llm.configured)
        return PolicyAgentStatus(
            enabled=self.enabled,
            llm_configured=configured,
            execution_strategy="规则基线 + 结构化大模型增强 + 证据校验 + 自动回退",
            agents=self.AGENTS,
        )

    async def analyze(
        self,
        document: PolicyDocument,
        candidates: Sequence[PolicyDocument] = (),
        *,
        allow_llm: bool = True,
    ) -> tuple[PolicyDocument, list[PolicyRelation]]:
        if not self.enabled:
            return document, []
        result = document.model_copy(deep=True)
        result.agent_runs = []
        use_llm = bool(allow_llm and result.content.strip() and self.llm and self.llm.configured)

        result, run = await self._document_agent(result, use_llm)
        result.agent_runs.append(run)
        result, run = await self._scope_agent(result, use_llm)
        result.agent_runs.append(run)
        result, run = await self._impact_agent(result, use_llm)
        result.agent_runs.append(run)
        relations, run = await self._relation_agent(result, candidates, use_llm)
        result.agent_runs.append(run)
        return result, relations

    async def _document_agent(
        self, document: PolicyDocument, use_llm: bool
    ) -> tuple[PolicyDocument, PolicyAgentRun]:
        started = perf_counter()
        clauses = _split_clauses(document.content)
        if clauses and not document.clauses:
            document.clauses = clauses
        match = _DOCUMENT_NUMBER_RE.search(document.content)
        if match and not document.document_number:
            document.document_number = match.group(0)
        output = await self.llm.understand_document(document) if use_llm and self.llm else None
        warnings: list[str] = []
        if output:
            if output.document_number and output.document_number in document.content:
                document.document_number = output.document_number
            elif output.document_number:
                warnings.append("模型文号未通过正文证据校验")
            if output.issuing_authorities:
                document.issuing_authorities = output.issuing_authorities
            if output.authority_level != AuthorityLevel.UNKNOWN:
                document.authority_level = output.authority_level
            if output.document_type != PolicyDocumentType.OTHER:
                document.document_type = output.document_type
            if output.lifecycle_status != PolicyLifecycleStatus.UNKNOWN:
                document.lifecycle_status = output.lifecycle_status
            document.is_red_head = output.is_red_head
            document.summary = output.summary or document.summary
            valid_clauses = [c for c in output.clauses if _supported(c.text, document.content)]
            if valid_clauses:
                document.clauses = valid_clauses
            mode, status, confidence = "hybrid", "completed", output.confidence
        else:
            mode, status, confidence = "rule", "fallback" if use_llm else "completed", 0.68
            if use_llm:
                warnings.append("大模型不可用，已使用规则结果")
        return document, _run(
            PolicyAgentName.DOCUMENT_UNDERSTANDING, status, mode,
            f"识别文号、发文机关、效力与 {len(document.clauses)} 个正文条款",
            confidence, len(document.clauses) + bool(document.document_number), started, warnings,
        )

    async def _scope_agent(
        self, document: PolicyDocument, use_llm: bool
    ) -> tuple[PolicyDocument, PolicyAgentRun]:
        started = perf_counter()
        scope = document.scope.model_copy(deep=True)
        evidence = _sentences_with(document.content, ("适用于", "适用范围", "支持对象", "申报主体"))
        if evidence:
            scope.evidence = [EvidenceQuote(excerpt=value, source_url=document.source_url) for value in evidence[:6]]
            scope.confidence = max(scope.confidence, 0.72)
        regions = _extract_regions(" ".join(evidence))
        if regions:
            scope.regions = regions
        targets = [term for term in ("企业", "事业单位", "社会组织", "项目单位", "科研机构") if term in " ".join(evidence)]
        if targets:
            scope.target_entities = targets
        dates = _DATE_RE.findall(" ".join(evidence))
        output = await self.llm.extract_scope(document) if use_llm and self.llm else None
        warnings: list[str] = []
        if output:
            cleaned = _validated_scope(output.scope, document.content)
            if cleaned.evidence:
                scope = cleaned
            else:
                warnings.append("模型适用范围缺少可验证正文证据，保留规则结果")
            mode, status = "hybrid", "completed"
        else:
            mode, status = "rule", "fallback" if use_llm else "completed"
            if use_llm:
                warnings.append("大模型不可用，已使用规则结果")
        document.scope = scope
        return document, _run(
            PolicyAgentName.SCOPE_EXTRACTION, status, mode,
            "提取地区、行业、主体、条件与期限", scope.confidence,
            len(scope.evidence), started, warnings + (["检测到期限日期"] if dates else []),
        )

    async def _impact_agent(
        self, document: PolicyDocument, use_llm: bool
    ) -> tuple[PolicyDocument, PolicyAgentRun]:
        started = perf_counter()
        impacts = document.impacts
        rule_impacts = _rule_impacts(document)
        if rule_impacts:
            impacts = rule_impacts
        output = await self.llm.analyze_impacts(document) if use_llm and self.llm else None
        warnings: list[str] = []
        if output:
            valid = [item for item in output.impacts if _impact_supported(item, document.content)]
            if valid:
                impacts = valid
            elif output.impacts:
                warnings.append("模型影响要点未通过正文证据校验，保留规则结果")
            mode, status = "hybrid", "completed"
        else:
            mode, status = "rule", "fallback" if use_llm else "completed"
            if use_llm:
                warnings.append("大模型不可用，已使用规则结果")
        document.impacts = impacts
        confidence = max((item.confidence for item in impacts), default=0.35)
        return document, _run(
            PolicyAgentName.IMPACT_ANALYSIS, status, mode,
            f"形成 {len(impacts)} 项支持、限制或合规影响", confidence,
            sum(len(item.evidence) for item in impacts), started, warnings,
        )

    async def _relation_agent(
        self, document: PolicyDocument, candidates: Sequence[PolicyDocument], use_llm: bool
    ) -> tuple[list[PolicyRelation], PolicyAgentRun]:
        started = perf_counter()
        relations = _rule_relations(document, candidates)
        output = await self.llm.reason_relations(document, candidates) if use_llm and self.llm else None
        warnings: list[str] = []
        if output:
            candidate_ids = {item.id for item in candidates if item.id != document.id}
            valid = [
                PolicyRelation(
                    source_id=document.id,
                    target_id=item.target_id,
                    relation=item.relation,
                    confidence=item.confidence,
                    evidence=item.evidence_excerpt,
                )
                for item in output.relations
                if item.target_id in candidate_ids and _supported(item.evidence_excerpt, document.content)
            ]
            if valid:
                relations = valid
            elif output.relations:
                warnings.append("模型关系缺少候选节点或正文证据，保留规则结果")
            mode, status = "hybrid", "completed"
        else:
            mode, status = "rule", "fallback" if use_llm else "completed"
            if use_llm:
                warnings.append("大模型不可用，已使用规则结果")
        confidence = max((item.confidence for item in relations), default=0.3)
        return relations, _run(
            PolicyAgentName.RELATION_REASONING, status, mode,
            f"发现 {len(relations)} 条依据、落实或替代关系", confidence,
            sum(bool(item.evidence) for item in relations), started, warnings,
        )


def _run(agent, status, mode, summary, confidence, evidence_count, started, warnings):
    return PolicyAgentRun(
        agent=agent, status=status, mode=mode, summary=summary,
        confidence=confidence, evidence_count=evidence_count,
        duration_ms=max(0, round((perf_counter() - started) * 1000)), warnings=warnings,
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _supported(excerpt: str, content: str) -> bool:
    return bool(excerpt.strip() and _normalize(excerpt) in _normalize(content))


def _split_clauses(content: str) -> list[PolicyClause]:
    paragraphs = [line.strip() for line in re.split(r"[\r\n]+", content) if line.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in re.split(r"(?<=[。；])", content) if part.strip()]
    clauses: list[PolicyClause] = []
    for index, paragraph in enumerate(paragraphs[:300], 1):
        heading = paragraph[:40] if _CLAUSE_HEADING_RE.match(paragraph) else ""
        clauses.append(PolicyClause(id=f"clause-{index}", order=index, heading=heading, text=paragraph))
    return clauses


def _sentences_with(content: str, terms: Sequence[str]) -> list[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？；])", content) if item.strip()]
    return list(dict.fromkeys(item for item in sentences if any(term in item for term in terms)))


def _extract_regions(content: str) -> list[str]:
    contextual = _REGION_CONTEXT_RE.findall(content)
    values = contextual or _REGION_RE.findall(content)
    return list(dict.fromkeys(values))


def _validated_scope(scope: PolicyScope, content: str) -> PolicyScope:
    valid = [item for item in scope.evidence if _supported(item.excerpt, content)]
    return scope.model_copy(update={"evidence": valid, "confidence": scope.confidence if valid else 0.0})


def _impact_supported(impact: PolicyImpact, content: str) -> bool:
    return bool(impact.evidence) and all(_supported(item.excerpt, content) for item in impact.evidence)


def _rule_impacts(document: PolicyDocument) -> list[PolicyImpact]:
    impacts: list[PolicyImpact] = []
    seen: set[str] = set()
    for sentence in _sentences_with(document.content, [item[0] for item in _IMPACT_TERMS]):
        for term, direction, action in _IMPACT_TERMS:
            if term not in sentence or action in seen:
                continue
            seen.add(action)
            impacts.append(PolicyImpact(
                id=f"impact-{document.id}-{len(impacts) + 1}", title=action,
                direction=direction, action=action,
                target="政策适用主体", summary=sentence[:180],
                industries=document.scope.industries,
                evidence=[EvidenceQuote(excerpt=sentence, source_url=document.source_url)],
                confidence=0.7,
            ))
            break
        if len(impacts) >= 12:
            break
    return impacts


def _rule_relations(
    document: PolicyDocument, candidates: Sequence[PolicyDocument]
) -> list[PolicyRelation]:
    relations: list[PolicyRelation] = []
    for candidate in candidates:
        if candidate.id == document.id:
            continue
        marker = candidate.document_number or candidate.title
        if marker and marker in document.content:
            evidence = next(
                (sentence for sentence in re.split(r"(?<=[。；])", document.content) if marker in sentence),
                marker,
            ).strip()
            relation = "localizes" if document.authority_level in {
                AuthorityLevel.PROVINCE, AuthorityLevel.CITY, AuthorityLevel.COUNTY
            } else "based_on"
            relations.append(PolicyRelation(
                source_id=document.id, target_id=candidate.id, relation=relation,
                confidence=0.82, evidence=evidence,
            ))
    return relations
