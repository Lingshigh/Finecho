import re
from collections.abc import Callable

from agent.llm import OptionalPolicyLLM
from agent.state import AnalysisState
from src.models.schemas import CompanyVerdict, GraphEdge, GraphNode
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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


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
        keywords = matched or re.findall(r"[\u4e00-\u9fff]{2,8}", request["policy_title"])[:5]
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
        warnings = list(state.get("warnings", []))
        if not companies:
            warnings.append("样例知识库未匹配到公司；请导入真实公司财报及产业链数据。")
        return {"companies": companies, "warnings": warnings}

    def verify_companies(state: AnalysisState) -> dict:
        query = " ".join([state["policy_summary"], *state["policy_keywords"], *state["products"]])
        verdicts: list[CompanyVerdict] = []
        for company in state["companies"]:
            evidence = rag.retrieve(company["id"], query)
            exposure = float(company.get("revenue_exposure", 0))
            rd_strength = min(1.0, float(company.get("rd_ratio", 0)) / 0.08)
            relevance = max((item.relevance for item in evidence), default=0.25)
            product_overlap = any(
                product in chain_node or chain_node in product
                for product in company.get("products", [])
                for chain_node in state["products"]
            )
            score = 0.55 * exposure + 0.2 * relevance + 0.15 * rd_strength
            score += 0.1 if product_overlap else 0
            if exposure < 0.05:
                score -= 0.2
            score = round(max(0.0, min(1.0, score)), 3)
            divergence = round(max(0.0, min(1.0, 1 - score + (0.15 if exposure < 0.05 else 0))), 3)
            if score >= 0.7 and divergence <= 0.4:
                verdict = "high_confidence"
            elif score < 0.4 or divergence >= 0.7:
                verdict = "hotspot_risk"
            else:
                verdict = "watch"
            reasons = [
                f"相关业务收入暴露度（样例）为 {exposure:.1%}",
                f"证据检索相关度最高为 {relevance:.0%}",
                "核心产品与政策传导节点存在交集" if product_overlap else "未发现强产品交集",
                f"主要约束：{company.get('capacity_constraint', '暂无数据')}",
            ]
            verdicts.append(
                CompanyVerdict(
                    company_id=company["id"],
                    company_name=company["name"],
                    ticker=company["ticker"],
                    verdict=verdict,
                    benefit_probability=score,
                    divergence_score=divergence,
                    revenue_exposure=exposure,
                    reasons=reasons,
                    evidence=evidence,
                )
            )
        return {"verdicts": verdicts}

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
        "verify_companies": verify_companies,
        "assemble_graph": assemble_graph,
    }
