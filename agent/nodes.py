import asyncio
import re
from collections.abc import Callable
from typing import Any

from agent.llm import OptionalPolicyLLM
from agent.state import AnalysisState
from src.models.schemas import CompanyCandidate, CompanyVerdict, GraphEdge, GraphNode
from src.services.rag_service import GraphRAGService

CHAIN_RULES: dict[str, tuple[list[str], list[str]]] = {
    "光伏": (["光伏", "新能源"], ["高纯晶硅", "硅片", "电池片", "光伏组件", "逆变器"]),
    "储能": (["储能", "新能源"], ["锂资源", "储能电池", "电池管理系统", "储能系统"]),
    "新能源汽车": (
        ["新能源汽车", "汽车零部件"],
        ["锂资源", "动力电池", "电机电控", "整车"],
    ),
    "人工智能": (["人工智能", "软件服务"], ["算力芯片", "服务器", "大模型", "行业应用"]),
    "半导体": (["半导体", "电子"], ["材料", "设备", "芯片设计", "晶圆制造", "封装测试"]),
    "机器人": (["机器人", "高端制造"], ["减速器", "伺服系统", "控制器", "本体", "系统集成"]),
}

# 宽松匹配使用的泛化产品词，覆盖供应链上中下游，保证每次放宽查询都会新增候选。
_BROAD_PRODUCTS = [
    "上游原材料",
    "核心零部件",
    "关键设备",
    "系统集成",
    "下游应用",
    "技术服务",
]

RELATED_INDUSTRY_RULES = {
    "新能源": "政策相关产业",
    "储能": "新能源",
    "新能源汽车": "汽车零部件",
    "人工智能": "软件服务",
    "半导体": "电子",
    "机器人": "高端制造",
}

# 多 agent 循环的默认上限，可在测试中注入覆盖。
DEFAULT_MAX_MATCH_ATTEMPTS = 3
DEFAULT_MAX_EVIDENCE_ATTEMPTS = 3

# 对抗式核验：规则分与 LLM 事实核查分的合成权重。
RULE_WEIGHT = 0.7
LLM_WEIGHT = 0.3
# LLM 立场 → 分数映射。
_LLM_STANCE_SCORE = {"support": 0.9, "neutral": 0.5, "challenge": 0.25}


def rule_score(
    *,
    exposure: float,
    rd_ratio: float,
    relevance: float,
    product_overlap: bool,
    has_evidence: bool,
) -> float:
    """基于财报暴露度、证据相关度、研发强度与产品交集的规则评分，与 LLM 核查无耦合。"""
    score = 0.55 * exposure + 0.2 * relevance + 0.15 * min(1.0, rd_ratio / 0.08)
    score += 0.1 if product_overlap else 0
    if exposure < 0.05:
        score -= 0.2
    if not has_evidence:
        score *= 0.8
    return round(max(0.0, min(1.0, score)), 3)


def blend_scores(rule: float, llm_stance: str | None) -> float:
    """规则分与 LLM 事实核查分按 0.7/0.3 加权合成；LLM 未配置或失败时用纯规则分。"""
    if llm_stance is None:
        return rule
    llm_score = _LLM_STANCE_SCORE[llm_stance]
    return round(max(0.0, min(1.0, RULE_WEIGHT * rule + LLM_WEIGHT * llm_score)), 3)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def route_match(state: AnalysisState) -> str:
    """没有匹配到公司且还有重试次数时，回退到 broaden_match 循环；否则继续验证。"""
    if not state.get("companies") and state.get("match_attempts", 0) < state.get(
        "max_match_attempts", DEFAULT_MAX_MATCH_ATTEMPTS
    ):
        return "broaden_match"
    return "form_candidate"


def _evidence_sufficient(state: AnalysisState) -> bool:
    """每个候选至少有一条相关度 >= 0.4 的证据才算充足；否则交由对抗式核验前先放宽检索。"""
    candidates = state.get("candidates", [])
    if not candidates:
        return True
    evidence = state.get("evidence", {})
    for candidate in candidates:
        items = evidence.get(candidate.company_id, [])
        if not items:
            return False
        if max((item.relevance for item in items), default=0) < 0.4:
            return False
    return True


def route_evidence(state: AnalysisState) -> str:
    """证据不足且还有重试次数时回退到 broaden_evidence；否则进入对抗式核验。"""
    if not _evidence_sufficient(state) and state.get("evidence_attempts", 0) < state.get(
        "max_evidence_attempts", DEFAULT_MAX_EVIDENCE_ATTEMPTS
    ):
        return "broaden_evidence"
    return "adversarial_check"


def build_nodes(rag: GraphRAGService, llm: OptionalPolicyLLM) -> dict[str, Callable]:
    async def extract_policy(state: AnalysisState) -> dict:
        request = state["request"]
        parsed = await llm.parse(request["policy_title"], request["policy_text"])
        if parsed:
            return {
                "policy_summary": parsed.summary,
                "policy_keywords": _unique(parsed.keywords),
                "industries": _unique(parsed.industries),
                "products": _unique(parsed.supply_chain_nodes),
            }

        text = f"{request['policy_title']} {request['policy_text']}"
        matched = [keyword for keyword in CHAIN_RULES if keyword in text]
        keywords = matched or re.findall(r"[一-鿿]{2,8}", request["policy_title"])[:5]
        summary = re.sub(r"\s+", " ", request["policy_text"]).strip()[:180]
        return {"policy_summary": summary, "policy_keywords": _unique(keywords)}

    def expand_chain(state: AnalysisState) -> dict:
        industries = list(state.get("industries", []))
        products = list(state.get("products", []))
        for keyword in state["policy_keywords"]:
            for rule_key, (rule_industries, rule_products) in CHAIN_RULES.items():
                if rule_key in keyword or keyword in rule_key:
                    industries.extend(rule_industries)
                    products.extend(rule_products)
        if not industries:
            industries = ["政策相关产业"]
        if not products:
            products = ["上游原材料", "核心设备", "下游应用"]
        return {"industries": _unique(industries), "products": _unique(products)}

    def match_companies(state: AnalysisState) -> dict:
        request = state["request"]
        companies = rag.find_companies(
            state["industries"], state["products"], request.get("target_companies")
        )
        return {"companies": companies}

    def broaden_match(state: AnalysisState) -> dict:
        """放宽匹配条件：行业阈值降至 0.7、追加泛化供应链词；若仍无候选则全量纳入样本库兜底。"""
        previous = {company["id"]: company for company in state.get("companies", [])}
        products = _unique([*state.get("products", []), *_BROAD_PRODUCTS])
        industries = list(state.get("industries", []))
        companies = rag.find_companies(industries, products, state["request"].get("target_companies"))
        if not companies:
            fallback = [item for item in rag.companies if item["id"] not in previous]
            if fallback:
                companies = fallback
        merged = _unique_ids([*previous.values(), *companies])
        changed = merged != state.get("companies", [])
        return {
            "products": products,
            "companies": merged,
            "industries": [
                RELATED_INDUSTRY_RULES.get(item, item) for item in state.get("industries", [])
            ],
            "match_attempts": state.get("match_attempts", 0) + 1,
            "warnings": [
                *state.get("warnings", []),
                (
                    "匹配公司较少，已放宽行业匹配阈值并补充泛化供应链词后重新检索。"
                    if changed
                    else "已放宽匹配条件，仍无新增公司，已全量纳入样本库公司供核验。"
                ),
            ],
        }

    def form_candidate(state: AnalysisState) -> dict:
        companies = state.get("companies", [])
        candidates = [
            CompanyCandidate(
                company_id=company["id"],
                name=company["name"],
                ticker=company["ticker"],
                reason=f"命中行业/产品查询词：{'、'.join(state.get('industries', []))}",
            )
            for company in companies
        ]
        return {"candidates": candidates}

    def gather_evidence(state: AnalysisState) -> dict:
        query = " ".join(
            [
                state.get("policy_summary", ""),
                *state.get("policy_keywords", []),
                *state.get("products", []),
            ]
        )
        evidence: dict[str, list[Any]] = {}
        for candidate in state["candidates"]:
            evidence[candidate.company_id] = rag.retrieve(candidate.company_id, query, limit=3)
        return {"evidence": evidence}

    def broaden_evidence(state: AnalysisState) -> dict:
        """证据不足时：向检索查询追加更宽泛的供应链词以扩大召回，不改动已生成的候选。"""
        products = _unique(
            [*state.get("products", []), *state.get("policy_keywords", []), *_BROAD_PRODUCTS]
        )
        return {
            "products": products,
            "evidence_attempts": state.get("evidence_attempts", 0) + 1,
            "warnings": [
                *state.get("warnings", []),
                "部分公司证据不足，已扩大检索范围并追加关键词后重试。",
            ],
        }

    async def adversarial_check(state: AnalysisState) -> dict:
        candidates = state["candidates"]
        companies_by_id = {company["id"]: company for company in state.get("companies", [])}
        policy_text = " ".join(
            [
                state.get("policy_summary", ""),
                *state.get("policy_keywords", []),
                *state.get("products", []),
            ]
        )
        verdicts: list[CompanyVerdict] = []
        warnings: list[str] = []

        # 1. 并行对每家候选调用 LLM 事实核查（未配置/无证据/失败时返回 None）。
        llm_checks = await asyncio.gather(
            *[
                llm.verify(
                    companies_by_id[candidate.company_id],
                    policy_text,
                    f"该公司的 {candidate.name} 应判为 {candidate.reason} 相关的高置信度受益标的。",
                    state["evidence"].get(candidate.company_id, []),
                )
                for candidate in candidates
            ]
        )
        llm_stances = [check.stance if check else None for check in llm_checks]

        # 2. 规则评分（纯函数），与 LLM 立场加权合成后给出最终判定。
        for candidate, stance, llm_check in zip(candidates, llm_stances, llm_checks, strict=True):
            company = companies_by_id[candidate.company_id]
            evidence = state["evidence"].get(candidate.company_id, [])
            if not evidence:
                warnings.append(f"未检索到 {company['name']} 的核验证据，判定信息有限。")
            rule = rule_score(
                exposure=float(company.get("revenue_exposure", 0)),
                rd_ratio=float(company.get("rd_ratio", 0)),
                relevance=max((item.relevance for item in evidence), default=0.25),
                product_overlap=any(
                    product in chain_node or chain_node in product
                    for product in company.get("products", [])
                    for chain_node in state.get("products", [])
                ),
                has_evidence=bool(evidence),
            )
            score = blend_scores(rule, stance)
            divergence = round(max(0.0, min(1.0, 1 - score + (0.15 if float(company.get("revenue_exposure", 0)) < 0.05 else 0))), 3)
            if score >= 0.7 and divergence <= 0.4:
                verdict = "high_confidence"
            elif score < 0.4 or divergence >= 0.7:
                verdict = "hotspot_risk"
            else:
                verdict = "watch"
            reasons = [
                f"相关业务收入暴露度（样例）为 {float(company.get('revenue_exposure', 0)):.1%}",
                f"证据检索相关度最高为 {max((item.relevance for item in evidence), default=0.25):.0%}",
                "核心产品与政策传导节点存在交集"
                if any(
                    product in chain_node or chain_node in product
                    for product in company.get("products", [])
                    for chain_node in state.get("products", [])
                )
                else "未发现强产品交集",
                f"主要约束：{company.get('capacity_constraint', '暂无数据')}",
            ]
            if llm_check is not None:
                reasons.append(
                    f"LLM 事实核查（{llm_check.stance}）：{llm_check.rationale}"
                )
            verdicts.append(
                CompanyVerdict(
                    company_id=company["id"],
                    company_name=company["name"],
                    ticker=company["ticker"],
                    verdict=verdict,
                    benefit_probability=score,
                    divergence_score=divergence,
                    revenue_exposure=float(company.get("revenue_exposure", 0)),
                    reasons=reasons,
                    evidence=evidence,
                )
            )
        return {
            "verdicts": verdicts,
            "warnings": [*state.get("warnings", []), *warnings],
        }

    def assemble_graph(state: AnalysisState) -> dict:
        request = state["request"]
        policy_id = f"policy:{state['task_id']}"
        nodes = [GraphNode(id=policy_id, label=request["policy_title"], type="policy", level=0)]
        edges: list[GraphEdge] = []
        for industry in state["industries"]:
            industry_id = f"industry:{industry}"
            nodes.append(GraphNode(id=industry_id, label=industry, type="industry", level=1))
            edges.append(
                GraphEdge(source=policy_id, target=industry_id, relation="impacts", weight=0.9)
            )
        for index, product in enumerate(state["products"]):
            product_id = f"chain:{product}"
            nodes.append(GraphNode(id=product_id, label=product, type="supply_chain", level=2))
            parent = f"industry:{state['industries'][index % len(state['industries'])]}"
            edges.append(
                GraphEdge(source=parent, target=product_id, relation="transmits", weight=0.8)
            )
        verdict_map = {item.company_id: item for item in state["verdicts"]}
        for index, company in enumerate(state["companies"]):
            verdict = verdict_map[company["id"]]
            nodes.append(
                GraphNode(
                    id=company["id"],
                    label=company["name"],
                    type="company",
                    level=3,
                    properties={
                        "ticker": company["ticker"],
                        "verdict": verdict.verdict,
                        "benefit_probability": verdict.benefit_probability,
                    },
                )
            )
            matching = [
                product
                for product in state["products"]
                if any(product in own or own in product for own in company.get("products", []))
            ]
            parent_product = (
                matching[0] if matching else state["products"][index % len(state["products"])]
            )
            edges.append(
                GraphEdge(
                    source=f"chain:{parent_product}",
                    target=company["id"],
                    relation="benefits",
                    weight=verdict.benefit_probability,
                    evidence_ids=[item.id for item in verdict.evidence],
                )
            )
        warnings = _unique(
            [*state.get("warnings", []), "当前结果使用演示财务证据，不构成投资建议。"]
        )
        return {"nodes": nodes, "edges": edges, "warnings": warnings}

    return {
        "extract_policy": extract_policy,
        "expand_chain": expand_chain,
        "match_companies": match_companies,
        "broaden_match": broaden_match,
        "form_candidate": form_candidate,
        "gather_evidence": gather_evidence,
        "broaden_evidence": broaden_evidence,
        "adversarial_check": adversarial_check,
        "assemble_graph": assemble_graph,
    }


def _unique_ids(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for company in companies:
        if company["id"] not in seen:
            seen.add(company["id"])
            result.append(company)
    return result
