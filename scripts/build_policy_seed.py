"""从权威机构政策聚合 HTML 构建 FinEcho 政策种子数据。

读取 C:\\Users\\28630\\Desktop\\html(1)\\ 下的 22 个政策原文聚合页，
解析出正式政策（过滤新闻/会议/人事），做跨机构去重与上下位关系推导，
按项目分层模型（AuthorityLevel / 文档类型 / Scope / Impact）结构化，
输出 data/policy_seed.json（PolicyDocument 数组）与 data/policy_relations.json。

用法:
    python scripts/build_policy_seed.py                # 从默认目录生成
    python scripts/build_policy_seed.py --source <dir> # 指定 HTML 目录

数据说明:
- 真实 HTML 结构与 policy_service._ITEM_RE 完全匹配，可直接复用现有解析逻辑；
- 新兴行业（AI/低空/储能/新能源/半导体/数据要素/绿色低碳/生物医药等）
  由 _infer_industries 识别，Scope/Impact 沿用项目现有分层模型。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.policy_schemas import (
    AuthorityLevel,
    PolicyDocument,
    PolicyRelation,
)
from src.services.policy_service import (
    _ITEM_RE,
    _document_from_index,
    _quarantine_reason,
)

# 机构文件 → (机构名, 默认层级)。空文件/导航页不产生政策。
AUTHORITY_FILES: dict[str, tuple[str, AuthorityLevel]] = {
    "authority_guowuyuan.html": ("国务院", AuthorityLevel.STATE_COUNCIL),
    "authority_ndrc.html": ("国家发展和改革委员会", AuthorityLevel.MINISTRY),
    "authority_nea.html": ("国家能源局", AuthorityLevel.MINISTRY),
    "authority_miit.html": ("工业和信息化部", AuthorityLevel.MINISTRY),
    "authority_mee.html": ("生态环境部", AuthorityLevel.MINISTRY),
    "authority_mem.html": ("应急管理部", AuthorityLevel.MINISTRY),
    "authority_mohurd.html": ("住房和城乡建设部", AuthorityLevel.MINISTRY),
    "authority_pbc.html": ("中国人民银行", AuthorityLevel.MINISTRY),
    "authority_samr.html": ("国家市场监督管理总局", AuthorityLevel.MINISTRY),
    "authority_spb.html": ("国家邮政局", AuthorityLevel.MINISTRY),
    "authority_nra.html": ("国家铁路局", AuthorityLevel.MINISTRY),
    "authority_caac.html": ("中国民用航空局", AuthorityLevel.MINISTRY),
    "authority_cac.html": ("国家互联网信息办公室", AuthorityLevel.MINISTRY),
    "authority_oscca.html": ("国家密码管理局", AuthorityLevel.MINISTRY),
    "authority_openstd.html": ("国家标准化管理委员会", AuthorityLevel.MINISTRY),
    "authority_gggzk.html": ("中央国家机关政府采购中心", AuthorityLevel.UNKNOWN),
    "authority_ithome.html": ("IT之家", AuthorityLevel.UNKNOWN),
    # 空文件（cnca/customs/gjzwfw/mps/nmpa）不列出。
}

# 机构文件 → 机构简称（用于 authority_name 传入 _document_from_index）。
AUTHORITY_NAMES: dict[str, str] = {
    "authority_guowuyuan.html": "国务院",
    "authority_ndrc.html": "国家发展改革委",
    "authority_nea.html": "国家能源局",
    "authority_miit.html": "工业和信息化部",
    "authority_mee.html": "生态环境部",
    "authority_mem.html": "应急管理部",
    "authority_mohurd.html": "住房和城乡建设部",
    "authority_pbc.html": "中国人民银行",
    "authority_samr.html": "国家市场监督管理总局",
    "authority_spb.html": "国家邮政局",
    "authority_nra.html": "国家铁路局",
    "authority_caac.html": "中国民用航空局",
    "authority_cac.html": "国家互联网信息办公室",
    "authority_oscca.html": "国家密码管理局",
    "authority_openstd.html": "国家标准化管理委员会",
    "authority_gggzk.html": "中央国家机关政府采购中心",
    "authority_ithome.html": "IT之家",
}

# 正式政策关键词：标题含其一即视为正式政策（与 policy_service._FORMAL_WORDS 对齐并扩展）。
_FORMAL_WORDS = (
    "通知", "意见", "办法", "条例", "规定", "规划", "方案", "公告",
    "决定", "批复", "标准", "细则", "规则", "指南", "行动", "令",
)

# 新兴行业关键词 → 行业标签（用于 _infer_industries 之外的人工补全，覆盖项目未预置的行业）。
INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "人工智能": ("人工智能", "AI", "大模型", "算力", "智能"),
    "低空经济": ("低空经济", "无人机", "通用航空", "航空"),
    "新型储能": ("储能", "电化学储能"),
    "新能源汽车": ("新能源汽车", "充电", "动力电池", "车船税", "电动汽车"),
    "氢能": ("氢能", "绿色燃料", "甲醇", "氢氟碳化物"),
    "半导体": ("半导体", "集成电路", "芯片", "布图设计"),
    "机器人": ("机器人", "具身智能"),
    "数字经济": ("数据要素", "数字化", "数字经济", "数据安全", "数据流通", "政务数据", "数据局"),
    "光伏": ("光伏", "可再生能源"),
    "生物医药": ("药品", "创新药", "医药", "医疗器械", "生物医药", "药监"),
    "绿色低碳": ("碳达峰", "碳中和", "节能降碳", "绿色低碳", "固体废物", "零碳", "能耗"),
    "智能航运": ("智能航运", "智慧交通"),
    "科技金融": ("科技金融", "绿色金融"),
}


def _enrich_industries(document: PolicyDocument) -> list[str]:
    """在项目 _infer_industries 基础上，用扩展关键词表补全新兴行业标签。

    匹配范围：标题 + 摘要 + 关键词（正文未抓取，只能凭标题与摘要）。
    """
    text = " ".join(
        [document.title, document.summary, *document.keywords]
    ).lower()
    inferred = list(document.scope.industries)
    for industry, terms in INDUSTRY_KEYWORDS.items():
        if industry in inferred:
            continue
        if any(term.lower() in text for term in terms):
            inferred.append(industry)
    # 保持唯一且稳定排序。
    return list(dict.fromkeys(inferred))

_WHITESPACE = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    """规范化标题用于去重：去空白、去省略号后缀、去文号括号、去尾部日期。"""
    value = _WHITESPACE.sub("", title)
    value = value.rstrip("….").strip()
    # 去掉标题末尾的文号括号，如《...》的通知(工信部信管〔2026〕3号)。
    value = re.sub(r"[（(][^（()）]*\d{2,4}[^（()）]*[）)]$", "", value)
    # 去尾部日期段（nra 拼接型），如 "...推进 07-15"。
    value = re.sub(r"\s?\d{2}-\d{2}$", "", value).strip()
    return value


def _core_title(title: str) -> str:
    """提取标题里的核心文件名（《》内），用于跨机构匹配同一政策。

    同政策在不同机构页面标题差异较大（发文机关前缀/文号后缀不同），
    但核心文件名《...》一致，如《新型电力系统建设"十五五"规划》。
    """
    inside = re.findall(r"《([^《》]+)》", title)
    if inside:
        return _WHITESPACE.sub("", inside[0])
    return _norm_title(title)


def _split_nra_title(title: str) -> str:
    """nra 标题拼接型（截断版+完整版+日期）取最长完整段。"""
    parts = re.split(r"\s{2,}", title)
    return max(parts, key=len).strip() if parts else title


def _is_formal(title: str) -> bool:
    """标题是否像正式政策（含正式文件关键词且未被 quarantine 拦截）。"""
    if _quarantine_reason(title):
        return False
    return any(word in title for word in _FORMAL_WORDS)


def _dedupe(items: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    """按规范化标题去重，优先保留标题含文号的条目（如发改能源〔2026〕942号版）。"""
    seen: dict[str, tuple[str, str, str, str]] = {}
    for item in items:
        title = item[2]
        key = _norm_title(title)
        if key not in seen:
            seen[key] = item
            continue
        existing = seen[key]
        # 新条目标题含文号而既有条目不含 → 替换为更完整的版本。
        if re.search(r"〔\[]\d{4}", title) and not re.search(r"〔\[]\d{4}", existing[2]):
            seen[key] = item
    return list(seen.values())


# 国务院"人工智能+"行动总纲标题（各"人工智能+X"实施意见的落实上位依据）。
_AI_MASTER_TITLE = "国务院关于深入实施“人工智能+”行动的意见"
# 综合能源体系规划核心名（电力系统/可再生能源等专项规划的落实上位依据）。
_ENERGY_MASTER_CORE = "新型能源体系建设“十五五”规划"
# 解读类标题标记。
_INTERPRET_MARKERS = ("解读", "答记者问", "一图读懂")


def _infer_relations(documents: list[PolicyDocument]) -> list[PolicyRelation]:
    """推断政策间的上下位关系：localizes / interprets / implements 三类。

    全部用入库文档的实际 id 建映射，保证关系不悬空；同源去重。
    """
    relations: list[PolicyRelation] = []
    by_id = {d.id: d for d in documents}
    core_ids: dict[str, list[str]] = {}
    for document in documents:
        core_ids.setdefault(_core_title(document.title), []).append(document.id)

    def _add(source_id: str, target_id: str, relation: str, evidence: str, confidence: float) -> None:
        if source_id == target_id:
            return
        if any(r.source_id == source_id and r.target_id == target_id and r.relation == relation for r in relations):
            return
        if source_id in by_id and target_id in by_id:
            relations.append(
                PolicyRelation(
                    source_id=source_id,
                    target_id=target_id,
                    relation=relation,
                    confidence=confidence,
                    evidence=evidence,
                )
            )

    # 1) localizes：部委页转发国务院政策库原文（同核心名、层级低于国务院）。
    guowuyuan_core: dict[str, str] = {}
    for document in documents:
        if document.authority_level == AuthorityLevel.STATE_COUNCIL:
            guowuyuan_core.setdefault(_core_title(document.title), document.id)
    for document in documents:
        if document.authority_level == AuthorityLevel.STATE_COUNCIL:
            continue
        target_id = guowuyuan_core.get(_core_title(document.title))
        if target_id:
            _add(
                document.id, target_id, "localizes",
                f"部委页转发国务院政策库原文《{document.title}》。", 0.8,
            )

    # 2) interprets：解读/答记者问 → 被解读政策（按《》核心名匹配）。
    for document in documents:
        if not any(mark in document.title for mark in _INTERPRET_MARKERS):
            continue
        core = _core_title(document.title)
        targets = [doc_id for doc_id in core_ids.get(core, []) if doc_id != document.id]
        # 优先指向正式政策（非解读类自身）。
        formal_targets = [
            doc_id for doc_id in targets
            if not any(mark in by_id[doc_id].title for mark in _INTERPRET_MARKERS)
        ]
        target = (formal_targets or targets)[0] if (formal_targets or targets) else None
        if target:
            _add(
                document.id, target, "interprets",
                f"对《{by_id[target].title}》的政策解读。", 0.7,
            )

    # 3a) implements：国务院"人工智能+X"实施意见/行动计划 → "人工智能+"行动总纲。
    ai_master = next(
        (d for d in documents if d.title.strip() == _AI_MASTER_TITLE), None
    )
    if ai_master:
        for document in documents:
            if document.id == ai_master.id:
                continue
            if re.search(r"人工智能\+[^\s“”]+", document.title) and any(
                word in document.title for word in ("实施意见", "行动计划", "行动方案")
            ):
                _add(
                    document.id, ai_master.id, "implements",
                    f"《{document.title}》落实国务院\"人工智能+\"行动总体部署。", 0.75,
                )

    # 3b) implements：能源领域专项规划（电力系统/可再生能源等）→ 综合能源体系规划。
    energy_master_ids = core_ids.get(_ENERGY_MASTER_CORE, [])
    if energy_master_ids:
        for document in documents:
            if document.id in energy_master_ids:
                continue
            core = _core_title(document.title)
            if any(mark in document.title for mark in _INTERPRET_MARKERS):
                continue  # 解读/答记者问不属于专项规划落实，交给 interprets 分支。
            if ("规划" in core and any(kw in core for kw in ("电力系统", "可再生能源", "节能降碳", "应对气候变化"))
                    and "能源体系" not in core):
                _add(
                    document.id, energy_master_ids[0], "implements",
                    f"《{document.title}》为能源领域专项规划，落实新型能源体系建设总体部署。", 0.7,
                )

    return relations


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 FinEcho 政策种子数据")
    parser.add_argument(
        "--source",
        default=r"C:\Users\28630\Desktop\html(1)",
        help="政策聚合 HTML 目录",
    )
    parser.add_argument(
        "--out",
        default=PROJECT_ROOT / "data",
        help="输出目录（data/）",
    )
    args = parser.parse_args()
    source_dir = Path(args.source)
    out_dir = Path(args.out)

    raw_items: list[tuple[str, str, str, str]] = []  # (file, url, title, date)
    for file_name, (authority, level) in AUTHORITY_FILES.items():
        path = source_dir / file_name
        if not path.exists():
            print(f"[skip] 缺失文件: {file_name}")
            continue
        html = path.read_text(encoding="utf-8")
        matches = _ITEM_RE.findall(html)
        for url, raw_title, raw_date in matches:
            title = _split_nra_title(_WHITESPACE.sub(" ", raw_title).strip())
            raw_items.append((file_name, url, title, raw_date.strip()))
        print(f"[read] {file_name}: {len(matches)} 条 ({authority})")

    # 过滤正式政策。
    formal = [item for item in raw_items if _is_formal(item[2])]
    print(f"\n原始条目 {len(raw_items)} → 正式政策 {len(formal)}")

    # guowuyuan 内部去重；部委页条目保留全部，跨机构重复交给下方引用分支。
    non_guowuyuan = [item for item in formal if item[0] != "authority_guowuyuan.html"]
    guowuyuan_only = [item for item in formal if item[0] == "authority_guowuyuan.html"]
    processed = [*_dedupe(guowuyuan_only), *non_guowuyuan]

    documents: list[PolicyDocument] = []
    relations: list[PolicyRelation] = []
    seen_urls: set[str] = set()
    seen_norm: set[str] = set()

    for file_name, url, title, raw_date in processed:
        norm = _norm_title(title)
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        authority = AUTHORITY_NAMES[file_name]
        level = AUTHORITY_FILES[file_name][1]
        document = _document_from_index(
            title=title,
            raw_date=raw_date,
            source_url=url,
            source_name=authority,
            authority_name=authority,
            default_level=level,
        )
        # 补全新兴行业标签（覆盖项目 _infer_industries 未预置的行业）。
        enriched = _enrich_industries(document)
        if enriched != document.scope.industries:
            document.scope = document.scope.model_copy(update={"industries": enriched})
        documents.append(document)

    # 关系推断（localizes / interprets / implements 三类自动关系）。
    relations = _infer_relations(documents)

    # 附加：guowuyuan 内部若同标题多版本，去重（保留含文号者）。
    print(f"去重后政策文档 {len(documents)} 份，引用关系 {len(relations)} 条")

    out_dir.mkdir(parents=True, exist_ok=True)
    seed_path = out_dir / "policy_seed.json"
    relations_path = out_dir / "policy_relations.json"
    seed_path.write_text(
        json.dumps([doc.model_dump(mode="json") for doc in documents], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    relations_path.write_text(
        json.dumps([rel.model_dump(mode="json") for rel in relations], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {seed_path}（{len(documents)} 份）与 {relations_path}（{len(relations)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
