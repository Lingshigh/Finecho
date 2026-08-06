"""产业研究报告规则模板引擎。

无 LLM 时（未配置 key / 依赖缺失 / API 故障）从分析结果数据组装专业研报：
四维度（政策影响传导/市场竞争格局/技术迭代路径/供应链风险）+ SWOT/波特五力/PEST
+ 数据来源标注。全部为纯同步函数，无 IO、不抛错；数据缺失只降级文案，绝不编造数字。
"""

from __future__ import annotations

from typing import Any

from src.models.schemas import (
    CompanyVerdict,
    GraphEdge,
    GraphNode,
    IndustryReport,
    ReportDimension,
    ReportFrameworkRow,
    ReportFrameworkTable,
    ReportRole,
    ReportSource,
)

# 四维度固定顺序。
DIMENSION_ORDER = (
    ("policy_transmission", "政策影响传导"),
    ("competition", "市场竞争格局"),
    ("technology", "技术迭代路径"),
    ("supply_chain", "供应链风险"),
)

_ROLE = ReportRole(
    name="行业研究分析师",
    perspective="以产业链传导为线索，结合财务与披露证据，给出政策受益方的结构性判断与风险提示。",
)


def _uniq(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _level_from_score(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _evidence_sources(verdicts: list[CompanyVerdict]) -> list[str]:
    """汇总所有核验证据的真实来源 URL（去重）。"""
    return _uniq(
        [item.source_url for verdict in verdicts for item in verdict.evidence if item.source_url]
    )


def _company_financials(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留带财务数据的公司（幻影科技等无财务样本跳过）。"""
    return [company for company in companies if company.get("financials")]


def _dimension_policy_transmission(
    *,
    policy_title: str,
    policy_summary: str,
    keywords: list[str],
    industries: list[str],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    verdicts: list[CompanyVerdict],
    source_url: str | None,
) -> ReportDimension:
    facts: list[str] = []
    sources: list[str] = []
    if source_url:
        sources.append(source_url)

    if keywords:
        facts.append(f"政策核心关键词：{'、'.join(keywords)}。")
    if industries:
        shown = industries[:4]
        facts.append(f"政策覆盖行业：{'、'.join(shown)}。")
    if edges:
        relation_counts: dict[str, int] = {}
        for edge in edges:
            relation_counts[edge.relation] = relation_counts.get(edge.relation, 0) + 1
        summary_line = "、".join(f"{rel} {count} 条" for rel, count in relation_counts.items())
        facts.append(f"图谱共识别 {len(edges)} 条传导关系：{summary_line}。")

        # 传导链样例：policy → industry → chain → company（取一条完整链路）。
        industry_ids = {node.id for node in nodes if node.type == "industry"}
        chain_ids = {node.id for node in nodes if node.type == "supply_chain"}
        by_id = {node.id: node for node in nodes}
        for edge in edges:
            if edge.source in industry_ids and edge.target in chain_ids:
                industry_label = by_id[edge.source].label
                chain_label = by_id[edge.target].label
                company = next(
                    (e for e in edges if e.source == edge.target), None
                )
                if company and company.target in by_id:
                    facts.append(
                        f"传导链示例：{policy_title} → {industry_label} → {chain_label} "
                        f"→ {by_id[company.target].label}。"
                    )
                else:
                    facts.append(
                        f"传导链示例：{policy_title} → {industry_label} → {chain_label}。"
                    )
                break

    sources.extend(_evidence_sources(verdicts))
    summary = (
        f"《{policy_title}》{policy_summary[:60]}，其影响沿行业→供应链→公司逐级传导。"
        if policy_summary
        else f"《{policy_title}》的影响沿行业→供应链→公司逐级传导。"
    )
    if not facts:
        facts.append("政策传导路径待补充专项数据。")
    return ReportDimension(
        name="政策影响传导",
        key="policy_transmission",
        summary=summary,
        key_facts=facts[:5],
        sources=_uniq(sources)[:6],
    )


def _dimension_competition(
    companies: list[dict[str, Any]], verdicts: list[CompanyVerdict], nodes: list[GraphNode], edges: list[GraphEdge]
) -> ReportDimension:
    facts: list[str] = []
    sources: list[str] = _evidence_sources(verdicts)
    with_fin = _company_financials(companies)

    ranked = sorted(
        with_fin,
        key=lambda c: float(c.get("financials", {}).get("revenue_2025", 0) or 0),
        reverse=True,
    )
    for index, company in enumerate(ranked, 1):
        revenue = company.get("financials", {}).get("revenue_2025")
        if revenue is None:
            continue
        facts.append(
            f"{index}. {company['name']}（{company['ticker']}）2025 营收 {revenue} 亿元，"
            f"样本{index}位（来源：2025年年度报告）。"
        )

    if ranked:
        profits = [
            float(c.get("financials", {}).get("net_profit_2025", 0) or 0) for c in with_fin
        ]
        profit_count = sum(1 for value in profits if value > 0)
        loss_count = sum(1 for value in profits if value < 0)
        if profit_count or loss_count:
            loss_names = [
                c["name"] for c, value in zip(with_fin, profits) if value < 0
            ]
            facts.append(
                f"盈利格局：样本中 {profit_count} 家盈利、{loss_count} 家亏损"
                + (f"（亏损集中于{'、'.join(loss_names)}）。" if loss_names else "。")
            )
        revenues = [
            float(c.get("financials", {}).get("revenue_2025", 0) or 0) for c in with_fin
        ]
        if revenues:
            median = sorted(revenues)[len(revenues) // 2] if revenues else 0
            top = max(revenues)
            ratio = top / median if median else 0
            concentration = "高" if ratio >= 3 else ("中" if ratio >= 1.5 else "低")
            facts.append(f"头部集中度：样本营收中位数约 {median:.0f} 亿元，头部为其中位数 {ratio:.1f} 倍，市场集中度{concentration}。")

    # 竞对关系：共享同一 chain 父节点的两家公司构成直接竞争。
    chain_to_companies: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation != "benefits":
            continue
        chain_to_companies.setdefault(edge.source, []).append(edge.target)
    for chain_id, company_ids in chain_to_companies.items():
        if len(company_ids) >= 2:
            chain_label = next(
                (node.label for node in nodes if node.id == chain_id), chain_id
            )
            names = [
                next(
                    (v.company_name for v in verdicts if v.company_id == cid), cid
                )
                for cid in company_ids[:3]
            ]
            facts.append(f"{'、'.join(names)} 在「{chain_label}」环节构成直接竞争。")

    if not facts:
        facts.append("样本公司财务数据有限，竞争格局判定基于营收相对排序。")
    return ReportDimension(
        name="市场竞争格局",
        key="competition",
        summary="基于样本公司 2025 年报营收与盈利数据的相对竞争地位分析。",
        key_facts=facts[:6],
        sources=_uniq(sources)[:6],
    )


def _dimension_technology(
    companies: list[dict[str, Any]], verdicts: list[CompanyVerdict], products: list[str]
) -> ReportDimension:
    facts: list[str] = []
    sources: list[str] = _evidence_sources(verdicts)
    with_fin = _company_financials(companies)

    rated = [
        (float(c.get("rd_ratio", 0) or 0), c) for c in with_fin
    ]
    rated.sort(key=lambda pair: pair[0], reverse=True)
    if rated:
        top_rd, top_company = rated[0]
        rd_expense = top_company.get("financials", {}).get("rd_expense_2025")
        expense_text = (
            f"，2025 研发投入 {rd_expense} 亿元" if rd_expense is not None else ""
        )
        facts.append(
            f"研发强度领先者：{top_company['name']}（研发费用率 {top_rd:.1%}{expense_text}）。"
        )
        avg_rd = sum(pair[0] for pair in rated) / len(rated)
        facts.append(f"样本平均研发费用率 {avg_rd:.1%}（来源：公司财务数据）。")

    if products:
        facts.append(f"技术主线：政策传导链涉及的关键产品环节为 {'、'.join(products[:5])}。")

    if not facts:
        facts.append("技术路线与研发投入详情建议查阅公司年报技术章节。")
    return ReportDimension(
        name="技术迭代路径",
        key="technology",
        summary="以研发强度与产业链技术环节为切入的技术演进判断。",
        key_facts=facts[:5],
        sources=_uniq(sources)[:6],
    )


def _dimension_supply_chain(
    companies: list[dict[str, Any]],
    verdicts: list[CompanyVerdict],
    products: list[str],
    rules_products: list[str],
) -> ReportDimension:
    facts: list[str] = []
    sources: list[str] = _evidence_sources(verdicts)

    for company in companies:
        constraint = company.get("capacity_constraint")
        if constraint:
            facts.append(f"{company['name']} 主要经营约束：{constraint}。")

    upstream = rules_products or products
    if upstream:
        facts.append(f"产业链上游关键环节：{'、'.join(upstream[:5])}。")

    inquiries = [
        item
        for verdict in verdicts
        for item in verdict.evidence
        if item.source_type == "inquiry" and item.source_url
    ]
    if inquiries:
        for item in inquiries[:2]:
            facts.append(f"监管问询关注点：{item.excerpt[:60]}。")
        sources.extend(item.source_url for item in inquiries)

    if not facts:
        facts.append("供应链风险主要基于公司披露的经营约束与问询证据。")
    return ReportDimension(
        name="供应链风险",
        key="supply_chain",
        summary="综合公司披露的经营约束、监管问询与产业链上游环节的风险评估。",
        key_facts=facts[:6],
        sources=_uniq(sources)[:6],
    )


def _build_swot(
    verdicts: list[CompanyVerdict],
    companies: list[dict[str, Any]],
    keywords: list[str],
    industries: list[str],
) -> ReportFrameworkTable:
    rows: list[ReportFrameworkRow] = []
    strengths = [
        v for v in verdicts if v.verdict == "high_confidence"
    ]
    weaknesses = [
        v for v in verdicts if v.verdict == "hotspot_risk"
    ]
    opportunities = keywords or industries
    threats = [
        c for c in companies
        if (float(c.get("revenue_exposure", 0) or 0) < 0.05)
        or (c.get("financials", {}).get("net_profit_2025") is not None
            and float(c.get("financials", {}).get("net_profit_2025", 0) or 0) < 0)
    ]

    if strengths:
        rows.append(
            ReportFrameworkRow(
                factor="优势（Strengths）",
                level=_level_from_score(
                    max(v.benefit_probability for v in strengths)
                ),
                statement=(
                    f"{len(strengths)} 家公司核验为高置信受益："
                    f"{'、'.join(v.company_name for v in strengths[:3])}（来源：核验结论）。"
                ),
            )
        )
    else:
        rows.append(ReportFrameworkRow(factor="优势（Strengths）", level="medium", statement="暂无高置信受益公司，建议结合专项调研补足。"))

    if weaknesses:
        rows.append(
            ReportFrameworkRow(
                factor="劣势（Weaknesses）",
                level=_level_from_score(
                    max(v.divergence_score for v in weaknesses)
                ),
                statement=(
                    f"{len(weaknesses)} 家公司存在蹭热点风险："
                    f"{'、'.join(v.company_name for v in weaknesses[:3])}（来源：核验结论）。"
                ),
            )
        )
    else:
        rows.append(ReportFrameworkRow(factor="劣势（Weaknesses）", level="medium", statement="当前样本未识别明显蹭热点风险。"))

    rows.append(
        ReportFrameworkRow(
            factor="机会（Opportunities）",
            level="high" if opportunities else "medium",
            statement=(
                f"政策驱动：{'、'.join(opportunities[:4])}（来源：政策文本）。"
                if opportunities
                else "政策关键词有限，机会面待补充专项分析。"
            ),
        )
    )

    threat_names = [c["name"] for c in threats]
    rows.append(
        ReportFrameworkRow(
            factor="威胁（Threats）",
            level="high" if threat_names else "medium",
            statement=(
                f"低暴露/亏损样本：{'、'.join(threat_names[:4])}（来源：公司财务数据）。"
                if threat_names
                else "当前样本未识别明显威胁项。"
            ),
        )
    )
    return ReportFrameworkTable(name="SWOT", rows=rows)


def _build_porter_five_forces(
    companies: list[dict[str, Any]], nodes: list[GraphNode], edges: list[GraphEdge]
) -> ReportFrameworkTable:
    material_companies = sum(
        1
        for c in companies
        if any(kw in (c.get("capacity_constraint", "") or "") for kw in ("材料", "价格", "上游"))
    )
    downstream_products = sum(
        1 for node in nodes if node.type == "supply_chain"
    )
    low_rd = sum(
        1
        for c in companies
        if (float(c.get("rd_ratio", 0) or 0) < 0.02)
    )
    loss_companies = sum(
        1
        for c in companies
        if (c.get("financials", {}).get("net_profit_2025") is not None
            and float(c.get("financials", {}).get("net_profit_2025", 0) or 0) < 0)
    )
    chain_to_companies: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation == "benefits":
            chain_to_companies.setdefault(edge.source, []).append(edge.target)
    competing_pairs = sum(1 for ids in chain_to_companies.values() if len(ids) >= 2)

    def _row(factor: str, signal: int, high_hint: str, low_hint: str) -> ReportFrameworkRow:
        if signal >= 2:
            level, statement = "high", high_hint
        elif signal == 1:
            level, statement = "medium", high_hint + "（信号较弱）"
        else:
            level, statement = "low", low_hint
        return ReportFrameworkRow(factor=factor, level=level, statement=statement)

    return ReportFrameworkTable(
        name="波特五力",
        rows=[
            _row(
                "供应商议价能力",
                material_companies,
                f"{material_companies} 家公司披露受上游材料/价格约束，供应商议价压力较高（来源：经营约束）。",
                "样本未披露显著上游材料依赖。",
            ),
            _row(
                "购买者议价能力",
                downstream_products,
                f"产业链下游环节 {downstream_products} 个，购买方选择面宽，议价能力较强（来源：产业链规则）。",
                "下游环节有限，购买者议价能力中等。",
            ),
            _row(
                "新进入者威胁",
                low_rd,
                f"{low_rd} 家公司研发强度低于 2%，技术门槛有限，新进入者威胁较高（来源：公司财务数据）。",
                "样本研发强度普遍较高，新进入者威胁较低。",
            ),
            _row(
                "替代品威胁",
                loss_companies,
                f"{loss_companies} 家样本公司处于亏损，行业盈利承压，替代路线风险上升（来源：公司财务数据）。",
                "样本盈利状况良好，替代品威胁较低。",
            ),
            _row(
                "现有竞争强度",
                competing_pairs,
                f"{competing_pairs} 组公司共享供应链环节，构成直接竞争（来源：图谱关系）。",
                "当前图谱未发现明显直接竞争对。",
            ),
        ],
    )


def _build_pest(
    companies: list[dict[str, Any]],
    keywords: list[str],
    industries: list[str],
    source_url: str | None,
) -> ReportFrameworkTable:
    with_fin = _company_financials(companies)
    profits = [
        float(c.get("financials", {}).get("net_profit_2025", 0) or 0) for c in with_fin
    ]
    profit_ratio = sum(1 for value in profits if value > 0) / len(profits) if profits else 0.0
    rated = [
        float(c.get("rd_ratio", 0) or 0) for c in with_fin
    ]
    avg_rd = sum(rated) / len(rated) if rated else 0.0
    top_rd_company = (
        max(with_fin, key=lambda c: float(c.get("rd_ratio", 0) or 0))["name"]
        if with_fin
        else "—"
    )

    return ReportFrameworkTable(
        name="PEST",
        rows=[
            ReportFrameworkRow(
                factor="政治（Political）",
                level="high" if keywords else "medium",
                statement=(
                    f"政策驱动明确：{'、'.join(keywords[:4])}"
                    + (f"（来源：{source_url}）" if source_url else "（来源：政策文本）。")
                ),
            ),
            ReportFrameworkRow(
                factor="经济（Economic）",
                level="high" if profit_ratio >= 0.5 else ("medium" if profit_ratio > 0 else "low"),
                statement=f"样本盈利公司占比 {profit_ratio:.0%}（来源：公司财务数据）。",
            ),
            ReportFrameworkRow(
                factor="社会（Social）",
                level="medium",
                statement=(
                    f"政策涉及行业：{'、'.join(industries[:4])}（来源：政策文本）。"
                    if industries
                    else "社会需求侧信息有限。"
                ),
            ),
            ReportFrameworkRow(
                factor="技术（Technological）",
                level="high" if avg_rd >= 0.05 else ("medium" if avg_rd >= 0.02 else "low"),
                statement=f"样本平均研发费用率 {avg_rd:.1%}，研发领先者为 {top_rd_company}（来源：公司财务数据）。",
            ),
        ],
    )


def build_rule_report(
    *,
    policy_title: str,
    policy_summary: str = "",
    keywords: list[str] | None = None,
    industries: list[str] | None = None,
    products: list[str] | None = None,
    nodes: list[GraphNode] | None = None,
    edges: list[GraphEdge] | None = None,
    verdicts: list[CompanyVerdict] | None = None,
    companies: list[dict[str, Any]] | None = None,
    source_url: str | None = None,
    rules_products: list[str] | None = None,
    related_policies: list[Any] | None = None,
    related_relations: list[Any] | None = None,
) -> IndustryReport:
    """从分析结果组装规则研报：四维度 + 三框架 + 来源标注。纯函数，不抛错。

    related_policies / related_relations 为政策库关联结果（PolicyBridgeService 产出），
    命中时在政策影响传导维度追加"政策库关联"事实，并在来源里补"政策库"条目。
    """
    keywords = keywords or []
    industries = industries or []
    products = products or []
    nodes = nodes or []
    edges = edges or []
    verdicts = verdicts or []
    companies = companies or []
    rules_products = rules_products or []
    related_policies = related_policies or []
    related_relations = related_relations or []

    dimensions = [
        _dimension_policy_transmission(
            policy_title=policy_title,
            policy_summary=policy_summary,
            keywords=keywords,
            industries=industries,
            nodes=nodes,
            edges=edges,
            verdicts=verdicts,
            source_url=source_url,
        ),
        _dimension_competition(companies, verdicts, nodes, edges),
        _dimension_technology(companies, verdicts, products),
        _dimension_supply_chain(companies, verdicts, products, rules_products),
    ]

    sources: list[ReportSource] = []
    if source_url:
        sources.append(ReportSource(label="政策原文", url=source_url))
    for verdict_url in _uniq(_evidence_sources(verdicts)):
        sources.append(ReportSource(label="公司披露证据", url=verdict_url))
    if companies:
        sources.append(ReportSource(label="公司财务数据（companies.json）"))
    if rules_products:
        sources.append(ReportSource(label="产业链规则表（chain_rules.json）"))

    # 政策库关联：命中同行业/关键词政策时，追加事实与来源。
    if related_policies:
        names = [item.title for item in related_policies[:5]]
        relation_count = len(related_relations)
        dimensions[0].key_facts.append(
            f"政策库关联：命中 {len(related_policies)} 份同行业/同主题政策，"
            f"其中 {relation_count} 条上下位关系（如 {'、'.join(names[:3])}）。"
        )
        for policy in related_policies[:6]:
            if policy.source_url:
                sources.append(
                    ReportSource(label="政策库关联", url=policy.source_url, detail=policy.title)
                )

    executive_summary = (
        f"《{policy_title}》沿{'、'.join(keywords[:3]) if keywords else '相关政策'}传导，"
        f"样本核验出 {sum(1 for v in verdicts if v.verdict == 'high_confidence')} 家高置信受益公司，"
        f"另有 {sum(1 for v in verdicts if v.verdict == 'hotspot_risk')} 家存在蹭热点风险；"
        f"行业竞争集中度{('高' if _concentration(companies) == 'high' else '中低')}，"
        f"供应链上游依赖{'、'.join(products[:3]) if products else '待补充'}。"
    )

    return IndustryReport(
        generated_by="rule",
        role=_ROLE,
        executive_summary=executive_summary,
        dimensions=dimensions,
        swot=_build_swot(verdicts, companies, keywords, industries),
        porter_five_forces=_build_porter_five_forces(companies, nodes, edges),
        pest=_build_pest(companies, keywords, industries, source_url),
        sources=sources,
    )


def _concentration(companies: list[dict[str, Any]]) -> str:
    revenues = sorted(
        float(c.get("financials", {}).get("revenue_2025", 0) or 0) for c in companies
    )
    if not revenues:
        return "low"
    median = revenues[len(revenues) // 2]
    ratio = max(revenues) / median if median else 0
    if ratio >= 3:
        return "high"
    if ratio >= 1.5:
        return "medium"
    return "low"


def _framework_rows(table: ReportFrameworkTable) -> list[str]:
    """把框架表折叠成 Markdown 行，供报告下载用。"""
    rows = [f"| {table.name}维度 | 强度 | 说明 |", "|---|---|---|"]
    for row in table.rows:
        rows.append(f"| {row.factor} | {row.level} | {row.statement} |")
    return rows
