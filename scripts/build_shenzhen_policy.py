"""抓取深圳市政府公开政策页，结构化后写入 data/shenzhen_policy.json。

设计：
- 数据源为深圳市政府政策文件公开页（默认 www.sz.gov.cn 政策法规栏目，可用 --source-url 覆盖）；
- 用与 policy_service._ITEM_RE 相同的结构正则提取 (url, title, date) 三元组；
- 逐条复用 policy_service._document_from_index 结构化（default_level=城市），
  并把 region 覆写为 ["深圳市"]（现有 _document_from_index 硬编码全国，无法表达深圳市）；
- 网络错误/解析失败静默跳过不崩，--dry-run 只预览。

用法:
    python scripts/build_shenzhen_policy.py                # 抓取并写入
    python scripts/build_shenzhen_policy.py --dry-run       # 只打印预览
    python scripts/build_shenzhen_policy.py --source-url <url>

依赖: httpx（已在 pyproject 运行时依赖）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.policy_schemas import AuthorityLevel, PolicyDocument
from src.services.policy_service import _ITEM_RE, _document_from_index

DEFAULT_SOURCE_URL = "https://www.sz.gov.cn/cn/xxgk/zfxxgj/zcfg/"

_WHITESPACE = re.compile(r"\s+")


def _clean_title(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def fetch_page(url: str) -> str:
    """GET 政策页并按 utf-8 解码；失败抛 httpx 异常由调用方兜底。"""
    response = httpx.get(url, timeout=20, follow_redirects=True)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_items(html: str) -> list[tuple[str, str, str]]:
    """用 _ITEM_RE 提取 (url, title, date) 三元组，清洗标题。"""
    return [
        (url, _clean_title(raw_title), raw_date.strip())
        for url, raw_title, raw_date in _ITEM_RE.findall(html)
    ]


def build_documents(
    items: list[tuple[str, str, str]], source_url: str
) -> list[PolicyDocument]:
    """把条目结构化为 PolicyDocument，region 覆写为深圳市。"""
    documents: list[PolicyDocument] = []
    for url, title, raw_date in items:
        if not title or not url:
            continue
        document = _document_from_index(
            title=title,
            raw_date=raw_date,
            source_url=url,
            source_name="深圳市政府",
            authority_name="深圳市人民政府办公厅",
            default_level=AuthorityLevel.CITY,
        )
        # 覆写为深圳市（_document_from_index 硬编码全国，无法表达城市）。
        document.scope = document.scope.model_copy(update={"regions": ["深圳市"]})
        documents.append(document)
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="深圳政策公开页 URL")
    parser.add_argument("--dry-run", action="store_true", help="只打印预览不写文件")
    args = parser.parse_args()

    try:
        html = fetch_page(args.source_url)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        print(f"抓取失败（{exc}），跳过。请检查网络或 --source-url。", file=sys.stderr)
        return 1

    items = parse_items(html)
    print(f"解析到 {len(items)} 条政策条目（来源 {args.source_url}）。")
    if not items:
        print("无条目（页面结构可能变更），未写文件。", file=sys.stderr)
        return 0

    documents = build_documents(items, args.source_url)
    for document in documents[:10]:
        print(f"  - {document.title[:50]} | {document.scope.regions}")

    if args.dry_run:
        print(f"\n[DRY-RUN] 共 {len(documents)} 份，未写入文件。")
        return 0

    out_path = PROJECT_ROOT / "data" / "shenzhen_policy.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(
            [doc.model_dump(mode="json") for doc in documents],
            handle, ensure_ascii=False, indent=2,
        )
    print(f"\n已写入 {out_path}（{len(documents)} 份）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
