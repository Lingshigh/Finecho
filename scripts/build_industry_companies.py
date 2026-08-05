"""用 AKShare 按行业动态拉取公司池，写入 data/companies.dynamic.json。

设计：
- 输入政策行业（默认取 INDUSTRY_TO_BOARD 的全部行业），映射到东财行业/概念板块，
  取板块成分股按总市值排序 top N（默认 5），复用 fetch_real_data.py 的财务/证据接口；
- products 用公司名/东财行业子串匹配规则 products（避免把全链条塞给每家公司），
  匹配不到兜底取规则 products[0]；
- 输出 companies.dynamic.json（含 akshare_industry / source 标记），由 GraphRAGService 增量加载。

用法:
    python scripts/build_industry_companies.py                 # 全部行业
    python scripts/build_industry_companies.py --industry 半导体 # 单行业
    python scripts/build_industry_companies.py --dry-run        # 只打印不写文件

依赖: pip install akshare
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# 政策行业名 → 东财行业/概念板块名（东财板块名与政策行业名不完全一致，需人工映射）。
INDUSTRY_TO_BOARD = {
    "半导体": "半导体",
    "机器人": "机器人概念",
    "光伏": "光伏设备",
    "人工智能": "AI 概念",
    "储能": "储能",
    "新能源汽车": "汽车整车",
}

# 每个行业从板块成分股里取 top N（按总市值）。
DEFAULT_TOP = 5


def _match_products(company_name: str, board_name: str, rule_products: list[str]) -> list[str]:
    """把公司映射到规则 products 的子集：用公司名/板块名子串匹配产品关键词，兜底取第一个。"""
    if not rule_products:
        return []
    text = f"{company_name} {board_name}"
    hits = [product for product in rule_products if product and product in text]
    return hits or [rule_products[0]]


def _build_industry(industry: str, top: int, dry_run: bool) -> list[dict]:
    import akshare as ak

    board_name = INDUSTRY_TO_BOARD[industry]
    from scripts.fetch_real_data import fetch_company_evidence, fetch_company_financials

    print(f"[{industry}] 板块: {board_name}")
    # 1. 板块成分股。
    try:
        cons = ak.stock_board_industry_cons_em(symbol=board_name)
    except (KeyError, ValueError, TypeError, ConnectionError) as exc:
        print(f"  警告：{board_name} 成分股接口失败（{exc}），跳过该行业。", file=sys.stderr)
        return []
    if cons is None or cons.empty:
        print(f"  警告：{board_name} 成分股为空，跳过。", file=sys.stderr)
        return []

    # 2. 按总市值排序取 top N。
    market_col = next(
        (col for col in ("总市值", "最新价", "代码") if col in cons.columns),
        "代码",
    )
    cons = cons.sort_values(market_col, ascending=False) if market_col in cons.columns else cons
    companies: list[dict] = []
    for _, row in cons.head(top).iterrows():
        code = str(row.get("代码", "")).zfill(6)
        name = str(row.get("名称", ""))
        if not code or not name:
            continue
        # 3. 财务（复用 fetch_real_data）。
        financials = fetch_company_financials(code, name, related_ratio=0.6)
        ticker = f"{code}.{'SH' if code.startswith('6') else 'SZ'}"
        # 4. 证据（复用 fetch_real_data）。
        evidence_keywords = [industry, board_name]
        hits = fetch_company_evidence(ticker, evidence_keywords)
        products = _match_products(name, board_name, ["材料", "设备", "芯片设计", "晶圆制造", "封装测试"])
        record = {
            "id": ticker,
            "ticker": ticker,
            "name": name,
            "industries": [industry],
            "products": products,
            "revenue_exposure": financials["revenue_exposure"],
            "rd_ratio": financials["rd_ratio"] or 0.03,
            "capacity_constraint": "AKShare 动态数据，经营约束待补充",
            "financials": financials["financials"],
            "evidence": hits[:2],
            "akshare_industry": board_name,
            "source": "akshare",
        }
        companies.append(record)
        print(f"  - {name}（{ticker}） 市值排名前列，products={products}")
    return companies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry", default=None, help="只处理单个行业（默认全部）")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="每行业取前 N 家公司")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = parser.parse_args()

    try:
        import akshare  # noqa: F401
    except ImportError:
        print("未安装 akshare。请先执行 pip install akshare。", file=sys.stderr)
        return 1

    industries = [args.industry] if args.industry else list(INDUSTRY_TO_BOARD)
    all_companies: list[dict] = []
    for industry in industries:
        all_companies.extend(_build_industry(industry, args.top, args.dry_run))

    print(f"\n共拉取 {len(all_companies)} 家动态公司。")
    if args.dry_run:
        print("[DRY-RUN] 未写入文件。")
        return 0

    out_path = DATA_DIR / "companies.dynamic.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(all_companies, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {out_path}（{len(all_companies)} 家）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
