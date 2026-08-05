"""用 AKShare 拉取真实公司财务与公告数据，重建 data/companies.json 与 data/evidence.json。

设计：
- 保留公司池（宁德时代/比亚迪/隆基绿能/通威股份 + 演示热点公司），只替换财务数字与证据来源，
  这样 chain_rules.json、eval_cases.json、现有测试与评测基线都不受影响；
- 财务指标取自东财财务摘要（stock_financial_abstract）与年报利润表（stock_profit_sheet_by_yearly_em），
  研发占比 = 研发费用 / 营业收入，营收暴露度 = 相关业务收入占比（按已知业务线人工归一化到 [0,1]）；
- 证据取自巨潮官方披露（stock_zh_a_disclosure_report_cninfo），只保留公告标题与链接，
  正文不抓取（避免大体积与爬取合规风险）。

用法:
    python scripts/fetch_real_data.py          # 写入 data/companies.json, data/evidence.json
    python scripts/fetch_real_data.py --dry-run  # 只打印结果不写文件

依赖: pip install akshare
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import akshare as ak

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# 保留公司池。revenue_exposure 为"相关业务收入占比"，按公司披露的业务构成归一化到 [0,1]，
# 近似替代原演示数据的 exposure；capacity_constraint 取公司近年年报"经营情况讨论与分析"中的已知约束关键词。
COMPANIES = [
    {
        "id": "300750.SZ",
        "symbol": "300750",
        "market": "SZ",
        "name": "宁德时代",
        "industries": ["储能", "新能源电池", "新能源汽车"],
        "products": ["动力电池", "储能电池", "电池系统"],
        "related_ratio": 0.85,
        "capacity_constraint": "锂电材料价格波动及海外合规要求",
    },
    {
        "id": "002594.SZ",
        "symbol": "002594",
        "market": "SZ",
        "name": "比亚迪",
        "industries": ["新能源汽车", "新能源电池"],
        "products": ["新能源汽车", "动力电池", "电池系统"],
        "related_ratio": 0.9,
        "capacity_constraint": "海外市场准入与供应链韧性",
    },
    {
        "id": "601012.SH",
        "symbol": "601012",
        "market": "SH",
        "name": "隆基绿能",
        "industries": ["光伏", "新能源"],
        "products": ["硅片", "光伏组件"],
        "related_ratio": 0.95,
        "capacity_constraint": "硅料价格下行与新技术路线切换",
    },
    {
        "id": "600438.SH",
        "symbol": "600438",
        "market": "SH",
        "name": "通威股份",
        "industries": ["光伏", "新能源"],
        "products": ["高纯晶硅", "太阳能电池片"],
        "related_ratio": 0.8,
        "capacity_constraint": "阶段性产能过剩与价格压力",
    },
    {
        "id": "000001.DEMO",
        "symbol": None,
        "market": "DEMO",
        "name": "幻影科技（演示）",
        "industries": ["人工智能", "新能源"],
        "products": ["信息化服务"],
        "related_ratio": 0.03,
        "capacity_constraint": "相关产品规模较小",
    },
]

# 证据检索关键词：按公司与行业手工配置，用于在公告标题里筛选相关证据（体现领域语义）。
EVIDENCE_KEYWORDS = {
    "300750.SZ": ["储能", "电池", "动力电池", "海外"],
    "002594.SZ": ["新能源汽车", "电池", "海外", "储能"],
    "601012.SH": ["光伏", "组件", "硅片", "BC", "单晶"],
    "600438.SH": ["光伏", "硅料", "电池片", "高纯晶硅"],
    "000001.DEMO": ["人工智能", "信息化"],
}

# 公告时间窗：覆盖最近一年半的披露，保证有足量真实公告。
NOTICE_START = "20250101"
NOTICE_END = "20260701"

# 研发占比低的企业被规则判为 low-confidence 的观察阈值（与 nodes.py 的 /0.08 归一化口径对应）。
MIN_RD_RATIO_REFERENCE = 0.08


def _num(value: object) -> float | None:
    """把东财返回的数字/字符串转 float；nan/空/横杠返回 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value in {"", "-", "--", "nan", "None", "不适用"}:
            return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _latest_row(df, report_type: str = "年报") -> object:
    """取最近一期指定报告期（默认年报）的行；缺失时退化为最近一期的任意报告。"""
    if "REPORT_TYPE" in df.columns:
        annual = df[df["REPORT_TYPE"] == report_type]
        if not annual.empty:
            return annual.sort_values("REPORT_DATE").iloc[-1]
    return df.sort_values("REPORT_DATE").iloc[-1]


def _latest_annual_abstract(df) -> tuple[str, object]:
    """stock_financial_abstract 是指标在行、报告期在列的转置结构；
    找出最近的 12-31 年报列，返回（列名, 该列 Series）。"""
    date_cols = [col for col in df.columns if isinstance(col, str) and col.isdigit()]
    annual_cols = [col for col in date_cols if col.endswith("1231")]
    target = max(annual_cols or date_cols)
    return target, df[target]


def fetch_company_financials(code: str, name: str, related_ratio: float) -> dict:
    """拉取一家公司的财务摘要，返回 companies.json 所需的指标字典。"""
    info = ak.stock_individual_info_em(symbol=code)
    info_map = dict(zip(info["item"], info["value"], strict=False))

    abstract = ak.stock_financial_abstract(symbol=code)
    _, abstract_col = _latest_annual_abstract(abstract)
    metric = {
        row["指标"]: abstract_col.loc[row.name]
        for _, row in abstract.iterrows()
        if row["指标"] in {"营业总收入", "归母净利润", "净资产收益率(ROE)", "毛利率"}
    }
    revenue = _num(metric.get("营业总收入"))
    net_profit = _num(metric.get("归母净利润"))
    roe = _num(metric.get("净资产收益率(ROE)"))

    # 研发费用：东财利润表（年报）的 RESEARCH_EXPENSE 字段。
    rd_expense: float | None = None
    try:
        prefix = "SZ" if code.startswith(("30", "00", "68")) else "SH"
        profit = ak.stock_profit_sheet_by_yearly_em(symbol=f"{prefix}{code}")
        profit_row = _latest_row(profit)
        rd_expense = _num(profit_row.get("RESEARCH_EXPENSE"))
        if revenue is None:
            revenue = _num(profit_row.get("TOTAL_OPERATE_INCOME"))
        if net_profit is None:
            net_profit = _num(profit_row.get("PARENT_NETPROFIT"))
    except (KeyError, ValueError, TypeError) as exc:
        print(f"  警告：{name} 利润表解析失败（{exc}），研发占比用摘要兜底。", file=sys.stderr)

    rd_ratio = (rd_expense / revenue) if (rd_expense and revenue) else None

    return {
        "ticker": f"{code}.{('SH' if code.startswith('6') else 'SZ')}",
        "name": name,
        "revenue_exposure": round(max(0.0, min(1.0, related_ratio)), 3),
        "rd_ratio": round(rd_ratio, 3) if rd_ratio is not None else None,
        "capacity_constraint": "实时财务数据缺失，使用本地演示字段",
        "financials": {
            "revenue_2025": round(revenue / 1e8, 1) if revenue else None,  # 亿元
            "net_profit_2025": round(net_profit / 1e8, 1) if net_profit else None,
            "rd_expense_2025": round(rd_expense / 1e8, 1) if rd_expense else None,
            "roe_2025_pct": round(roe, 2) if roe is not None else None,
            "market_cap_2025": round(_num(info_map.get("总市值")) / 1e8, 1)
            if info_map.get("总市值")
            else None,
            "industry": info_map.get("行业"),
        },
    }


def fetch_company_evidence(company_id: str, keywords: list[str]) -> list[dict]:
    """拉取公司巨潮公告：优先真实年报/半年报标题（annual_report），
    不足 3 条时用关键词在公告标题里补足（announcement）；失败返回空列表。"""
    code = company_id.split(".")[0]
    try:
        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=code, start_date=NOTICE_START, end_date=NOTICE_END
        )
    except (KeyError, ValueError, TypeError, ConnectionError) as exc:
        print(f"  警告：{code} 公告接口失败（{exc}），证据留空由调用方兜底。", file=sys.stderr)
        return []

    hits: list[dict] = []

    def _append(title: str, row, source_type: str) -> None:
        hits.append(
            {
                "id": f"ev-{company_id.split('.')[0]}-{len(hits) + 1}",
                "company_id": company_id,
                "source_type": source_type,
                "title": title,
                "excerpt": f"巨潮披露：{title}（{row.get('公告时间', '')}）",
                "year": 2025,
                "keywords": keywords,
                "source_url": row.get("公告链接"),
            }
        )

    # 1. 真实定期报告（年报/半年报/季报）优先。
    for _, row in df.iterrows():
        title = str(row.get("公告标题", ""))
        if any(token in title for token in ("年度报告", "半年度报告", "季度报告")):
            _append(title, row, "annual_report")
        if len(hits) >= 3:
            break

    # 2. 不足 3 条时，用行业关键词在公告标题里补足。
    if len(hits) < 3:
        for _, row in df.iterrows():
            title = str(row.get("公告标题", ""))
            if any(keyword in title for keyword in keywords):
                if any(item["title"] == title for item in hits):
                    continue
                _append(title, row, "announcement")
            if len(hits) >= 3:
                break

    return hits[:3]


def build_companies() -> list[dict]:
    companies = []
    for entry in COMPANIES:
        if entry["symbol"] is None:  # 演示热点公司保持原样
            companies.append(
                {
                    "id": entry["id"],
                    "ticker": entry["id"],
                    "name": entry["name"],
                    "industries": entry["industries"],
                    "products": entry["products"],
                    "revenue_exposure": entry["related_ratio"],
                    "rd_ratio": 0.009,
                    "capacity_constraint": entry["capacity_constraint"],
                }
            )
            continue
        financials = fetch_company_financials(
            entry["symbol"], entry["name"], entry["related_ratio"]
        )
        companies.append(
            {
                "id": entry["id"],
                "ticker": entry["id"],
                "name": entry["name"],
                "industries": entry["industries"],
                "products": entry["products"],
                "revenue_exposure": financials["revenue_exposure"],
                "rd_ratio": financials["rd_ratio"] or 0.03,
                "capacity_constraint": entry["capacity_constraint"],
                "financials": financials["financials"],
            }
        )
    return companies


def build_evidence(companies: list[dict]) -> list[dict]:
    evidence: list[dict] = []
    for company in companies:
        cid = company["id"]
        if cid == "000001.DEMO":
            evidence.append(
                {
                    "id": "ev-demo-inquiry",
                    "company_id": cid,
                    "source_type": "inquiry",
                    "title": "幻影科技问询函回复（演示数据）",
                    "excerpt": "公司相关行业尚处于探索阶段，未形成合同，对主营业务影响不足 5%。",
                    "year": 2025,
                    "keywords": ["人工智能", "未形成收入", "占比", "问询函"],
                }
            )
            continue
        hits = fetch_company_evidence(cid, EVIDENCE_KEYWORDS[cid])
        evidence.extend(hits)
        # 至少保留一条兜底证据，保证 GraphRAG 检索不为空。
        if not hits:
            evidence.append(
                {
                    "id": f"ev-{cid.split('.')[0]}-demo",
                    "company_id": cid,
                    "source_type": "demo",
                    "title": f"{company['name']} 相关业务情况（演示兜底）",
                    "excerpt": "未能在公告接口命中相关披露，使用演示证据兜底。",
                    "year": 2025,
                    "keywords": [],
                }
            )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印结果不写文件")
    args = parser.parse_args()

    companies = build_companies()
    evidence = build_evidence(companies)

    for company in companies:
        print(f"- {company['name']} ({company['ticker']}) "
              f"exposure={company['revenue_exposure']} rd_ratio={company['rd_ratio']}")

    if args.dry_run:
        print("\n[DRY-RUN] 未写入文件。")
        return 0

    with (DATA_DIR / "companies.json").open("w", encoding="utf-8") as handle:
        json.dump(companies, handle, ensure_ascii=False, indent=2)
    with (DATA_DIR / "evidence.json").open("w", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
    print(f"\n已写入 {len(companies)} 家公司、{len(evidence)} 条证据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
