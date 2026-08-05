import hashlib
import html as html_module
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from src.models.policy_schemas import (
    AuthenticityGrade,
    AuthorityLevel,
    EvidenceQuote,
    PolicyAgentAnalysisResponse,
    PolicyAgentStatus,
    PolicyDocument,
    PolicyDocumentImportRequest,
    PolicyDocumentType,
    PolicyImpact,
    PolicyImportRequest,
    PolicyImportResult,
    PolicyLifecycleStatus,
    PolicyListResponse,
    PolicyRelation,
    PolicyScope,
    PolicyStats,
    QuarantinedItem,
)
from src.repositories.policy_repository import InMemoryPolicyRepository, build_facets
from src.services.policy_agents import PolicyAgentOrchestrator

_ITEM_RE = re.compile(
    r'<div class="item">\s*<div class="t">.*?'
    r'<a href="([^"]*)"[^>]*>(.*?)</a>.*?'
    r'<div class="meta">\s*([^<]+)',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_WORDS = (
    "会议",
    "召开",
    "会见",
    "活动",
    "大赛",
    "微博",
    "微信",
    "网站",
    "备案",
    "学习",
    "调研",
    "座谈",
    "表彰",
    "考察",
    "访问",
)
_FORMAL_WORDS = (
    "通知",
    "意见",
    "办法",
    "条例",
    "规定",
    "规划",
    "方案",
    "公告",
    "决定",
    "批复",
    "标准",
    "细则",
    "规则",
    "指南",
)
_INDUSTRY_TERMS = {
    "储能": ("储能", "储能电池", "电池管理系统", "系统集成"),
    "新能源": ("新能源", "可再生能源", "光伏", "风电"),
    "电力": ("电力系统", "电网", "绿电", "发电"),
    "人工智能": ("人工智能", "AI", "智能化"),
    "低空经济": ("低空经济", "航空运输", "无人机"),
    "绿色低碳": ("绿色低碳", "节能降碳", "碳达峰", "碳中和"),
}


class PolicyService:
    def __init__(
        self,
        repository: InMemoryPolicyRepository,
        agents: PolicyAgentOrchestrator | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.repository = repository
        self.agents = agents or PolicyAgentOrchestrator()
        self.data_dir = data_dir
        self._quarantine: list[QuarantinedItem] = []

    async def bootstrap(self) -> None:
        seeds = _seed_documents()
        enriched: list[PolicyDocument] = []
        for document in seeds:
            result, _ = await self.agents.analyze(document, seeds, allow_llm=False)
            enriched.append(result)
        await self.repository.upsert_many(enriched)
        for relation in _seed_relations():
            await self.repository.add_relation(relation)
        # 追加真实政策种子（data/policy_seed.json + policy_relations.json），保留演示种子。
        if self.data_dir is not None:
            await self._load_real_seed()
            await self._load_optional_seed("shenzhen_policy.json")

    async def _load_optional_seed(self, name: str) -> None:
        """加载可选政策种子文件（如深圳政策），结构对齐 PolicyDocument；缺失/非法时静默跳过。"""
        path = self.data_dir / name
        if not path.exists():
            return
        import json as _json

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = _json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(payload, list):
            return
        documents = [PolicyDocument.model_validate(item) for item in payload]
        await self.repository.upsert_many(documents)

    async def _load_real_seed(self) -> None:
        """加载 scripts/build_policy_seed.py 生成的真实政策种子，追加到内存仓库。

        文件缺失时静默跳过（首次 clone 无 data 产物时仍可运行演示数据）。
        """
        seed_path = self.data_dir / "policy_seed.json"
        if not seed_path.exists():
            return
        import json as _json

        with seed_path.open("r", encoding="utf-8") as handle:
            payload = _json.load(handle)
        if not isinstance(payload, list):
            return
        documents = [PolicyDocument.model_validate(item) for item in payload]
        await self.repository.upsert_many(documents)
        relations_path = self.data_dir / "policy_relations.json"
        if relations_path.exists():
            with relations_path.open("r", encoding="utf-8") as handle:
                relations_payload = _json.load(handle)
            for item in relations_payload or []:
                await self.repository.add_relation(PolicyRelation.model_validate(item))

    async def list(
        self,
        *,
        q: str = "",
        authority_level: AuthorityLevel | None = None,
        document_type: PolicyDocumentType | None = None,
        lifecycle_status: PolicyLifecycleStatus | None = None,
        authenticity_grade: AuthenticityGrade | None = None,
        industry: str = "",
        region: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> PolicyListResponse:
        documents = await self.repository.all()
        query = q.strip().lower()

        def matches(item: PolicyDocument) -> bool:
            haystack = " ".join(
                [
                    item.title,
                    item.summary,
                    item.document_number or "",
                    *item.issuing_authorities,
                    *item.keywords,
                ]
            ).lower()
            return all(
                (
                    not query or query in haystack,
                    authority_level is None or item.authority_level == authority_level,
                    document_type is None or item.document_type == document_type,
                    lifecycle_status is None or item.lifecycle_status == lifecycle_status,
                    authenticity_grade is None
                    or item.authenticity_grade == authenticity_grade,
                    not industry or industry in item.scope.industries,
                    not region or region in item.scope.regions,
                )
            )

        filtered = [item for item in documents if matches(item)]
        filtered.sort(key=lambda item: item.publish_date or date.min, reverse=True)
        start = (page - 1) * page_size
        return PolicyListResponse(
            items=filtered[start : start + page_size],
            total=len(filtered),
            page=page,
            page_size=page_size,
            facets=build_facets(documents),
        )

    async def get(self, policy_id: str) -> PolicyDocument:
        return await self.repository.get(policy_id)

    async def lineage(self, policy_id: str):
        return await self.repository.lineage(policy_id)

    async def stats(self) -> PolicyStats:
        documents = await self.repository.all()
        return PolicyStats(
            total=len(documents),
            formal_documents=sum(
                item.document_type
                not in {PolicyDocumentType.NEWS, PolicyDocumentType.INTERPRETATION}
                and item.authenticity_grade != AuthenticityGrade.QUARANTINED
                for item in documents
            ),
            pending_review=sum(
                any(impact.review_status == "pending" for impact in item.impacts)
                for item in documents
            ),
            quarantined=len(self._quarantine),
            central_documents=sum(
                item.authority_level
                in {AuthorityLevel.CENTRAL, AuthorityLevel.STATE_COUNCIL}
                for item in documents
            ),
            local_documents=sum(
                item.authority_level
                in {AuthorityLevel.PROVINCE, AuthorityLevel.CITY, AuthorityLevel.COUNTY}
                for item in documents
            ),
        )

    async def import_html(self, payload: PolicyImportRequest) -> PolicyImportResult:
        documents: list[PolicyDocument] = []
        quarantine: list[QuarantinedItem] = []
        for url, raw_title, raw_date in _ITEM_RE.findall(payload.html):
            title = _clean_text(raw_title)
            source_url = url or (str(payload.source_url) if payload.source_url else None)
            reason = _quarantine_reason(title)
            if reason:
                quarantine.append(QuarantinedItem(title=title, url=source_url, reason=reason))
                continue
            documents.append(
                _document_from_index(
                    title=title,
                    raw_date=raw_date.strip(),
                    source_url=source_url,
                    source_name=payload.source_name,
                    authority_name=payload.authority_name,
                    default_level=payload.default_authority_level,
                )
            )

        candidates = [*await self.repository.all(), *documents]
        enriched: list[PolicyDocument] = []
        for document in documents:
            result, relations = await self.agents.analyze(
                document, candidates, allow_llm=False
            )
            enriched.append(result)
            for relation in relations:
                await self.repository.add_relation(relation)
        documents = enriched
        created, updated = await self.repository.upsert_many(documents)
        self._quarantine.extend(quarantine)
        return PolicyImportResult(
            imported=created,
            updated=updated,
            quarantined=len(quarantine),
            documents=documents,
            quarantine_items=quarantine,
        )

    async def import_document(
        self, payload: PolicyDocumentImportRequest
    ) -> PolicyAgentAnalysisResponse:
        source_url = str(payload.source_url) if payload.source_url else None
        document = _document_from_index(
            title=payload.title,
            raw_date="",
            source_url=source_url,
            source_name=payload.source_name,
            authority_name=payload.authority_name,
            default_level=payload.default_authority_level,
        ).model_copy(
            update={
                "content": payload.content,
                "summary": "等待政策 Agent 从正文提取结构化摘要。",
                "quality_warnings": [],
            }
        )
        candidates = await self.repository.all()
        document, relations = await self.agents.analyze(
            document, candidates, allow_llm=True
        )
        if payload.persist:
            await self.repository.upsert(document)
            for relation in relations:
                await self.repository.add_relation(relation)
        return PolicyAgentAnalysisResponse(
            document=document,
            relations=relations,
            persisted=payload.persist,
        )

    def agent_status(self) -> PolicyAgentStatus:
        return self.agents.status()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(_TAG_RE.sub("", value))).strip()


def _quarantine_reason(title: str) -> str | None:
    if not title:
        return "标题为空"
    if "…" in title or title.endswith("..."):
        return "标题被截断，需重新抓取详情页"
    if any(word in title for word in _NOISE_WORDS) and not any(
        word in title for word in _FORMAL_WORDS
    ):
        return "会议、活动或站点导航内容，不属于正式政策"
    if not any(word in title for word in _FORMAL_WORDS):
        return "未识别到正式政策文件特征"
    return None


def _parse_date(raw: str) -> date | None:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if not match:
        return None
    try:
        return date(*(int(value) for value in match.groups()))
    except ValueError:
        return None


def _document_id(title: str, source_url: str | None) -> str:
    fingerprint = f"{title}|{source_url or ''}".encode()
    return f"policy-{hashlib.sha1(fingerprint).hexdigest()[:12]}"


def _classify_type(title: str) -> PolicyDocumentType:
    if "征求意见" in title:
        return PolicyDocumentType.DRAFT
    if "解读" in title or "答记者问" in title:
        return PolicyDocumentType.INTERPRETATION
    for word, document_type in (
        ("条例", PolicyDocumentType.REGULATION),
        ("规划", PolicyDocumentType.PLAN),
        ("方案", PolicyDocumentType.PLAN),
        ("意见", PolicyDocumentType.OPINION),
        ("办法", PolicyDocumentType.MEASURE),
        ("标准", PolicyDocumentType.STANDARD),
        ("公告", PolicyDocumentType.ANNOUNCEMENT),
        ("通知", PolicyDocumentType.NOTICE),
    ):
        if word in title:
            return document_type
    return PolicyDocumentType.OTHER


def _infer_industries(text: str) -> list[str]:
    return [
        industry
        for industry, terms in _INDUSTRY_TERMS.items()
        if any(term.lower() in text.lower() for term in terms)
    ]


def _infer_keywords(text: str) -> list[str]:
    candidates = [term for terms in _INDUSTRY_TERMS.values() for term in terms]
    return list(dict.fromkeys(term for term in candidates if term.lower() in text.lower()))


def _infer_impact(title: str, policy_id: str, source_url: str | None) -> list[PolicyImpact]:
    industries = _infer_industries(title)
    if not industries:
        return []
    direction: str = "neutral"
    action = "规范引导"
    if any(word in title for word in ("促进", "加快", "推动", "支持")):
        direction = "support"
        action = "鼓励发展"
    elif any(word in title for word in ("限制", "禁止", "淘汰")):
        direction = "restrict"
        action = "限制约束"
    return [
        PolicyImpact(
            id=f"impact-{policy_id}",
            title=f"{industries[0]}领域政策传导",
            direction=direction,
            action=action,
            target="相关行业与项目主体",
            summary="基于索引标题形成的候选影响，需在抓取正文后按具体条款复核。",
            industries=industries,
            chain_nodes=_chain_nodes(industries),
            evidence=[EvidenceQuote(excerpt=title, source_url=source_url)],
            confidence=0.58,
        )
    ]


def _chain_nodes(industries: Iterable[str]) -> list[str]:
    mapping = {
        "储能": ["上游材料", "储能电池", "电池管理系统", "系统集成"],
        "新能源": ["关键设备", "新能源开发", "并网消纳"],
        "电力": ["电源侧", "电网侧", "用户侧"],
        "人工智能": ["算力基础设施", "模型与软件", "行业应用"],
        "低空经济": ["航空器", "基础设施", "运营服务"],
        "绿色低碳": ["节能设备", "绿色制造", "碳管理服务"],
    }
    return list(dict.fromkeys(node for industry in industries for node in mapping.get(industry, [])))


def _document_from_index(
    *,
    title: str,
    raw_date: str,
    source_url: str | None,
    source_name: str,
    authority_name: str,
    default_level: AuthorityLevel,
) -> PolicyDocument:
    policy_id = _document_id(title, source_url)
    publish_date = _parse_date(raw_date)
    industries = _infer_industries(title)
    lifecycle = (
        PolicyLifecycleStatus.DRAFT if "征求意见" in title else PolicyLifecycleStatus.UNKNOWN
    )
    official = bool(source_url and ("gov.cn" in source_url or ".gov.cn" in source_url))
    warnings = ["当前记录来自索引页，正文、文号、效力状态仍需二次核验"]
    if publish_date and publish_date.day == 1:
        warnings.append("发布日期为月初占位值的可能性较高，需从详情页复核")
    return PolicyDocument(
        id=policy_id,
        title=title,
        issuing_authorities=[authority_name],
        authority_level=default_level,
        document_type=_classify_type(title),
        lifecycle_status=lifecycle,
        publish_date=publish_date,
        source_name=source_name,
        source_url=source_url,
        authenticity_grade=AuthenticityGrade.B if official else AuthenticityGrade.C,
        summary="由政策索引导入的候选正式文件，等待正文采集与人工复核。",
        scope=PolicyScope(
            regions=["全国"]
            if default_level
            in {AuthorityLevel.CENTRAL, AuthorityLevel.STATE_COUNCIL, AuthorityLevel.MINISTRY}
            else [],
            industries=industries,
            target_entities=["相关行业与项目主体"] if industries else [],
            evidence=[EvidenceQuote(excerpt=title, source_url=source_url)],
            confidence=0.55 if industries else 0.2,
        ),
        impacts=_infer_impact(title, policy_id, source_url),
        keywords=_infer_keywords(title),
        quality_warnings=warnings,
    )


def _seed_document(
    *,
    policy_id: str,
    title: str,
    publish_date: date,
    source_url: str,
    authorities: list[str],
    level: AuthorityLevel,
    document_type: PolicyDocumentType,
    industries: list[str],
    summary: str,
) -> PolicyDocument:
    impact = PolicyImpact(
        id=f"impact-{policy_id}",
        title=f"{industries[0]}政策传导" if industries else "政策传导",
        direction="support",
        action="规划引导",
        target="相关行业、项目单位与实施主体",
        summary="依据标题与官方索引形成的候选影响结论，正文条款接入后进一步细化。",
        industries=industries,
        chain_nodes=_chain_nodes(industries),
        evidence=[EvidenceQuote(excerpt=title, source_url=source_url)],
        confidence=0.62,
    )
    return PolicyDocument(
        id=policy_id,
        title=title,
        issuing_authorities=authorities,
        authority_level=level,
        document_type=document_type,
        lifecycle_status=PolicyLifecycleStatus.UNKNOWN,
        publish_date=publish_date,
        source_name="中国政府网政策库",
        source_url=source_url,
        authenticity_grade=AuthenticityGrade.B,
        summary=summary,
        scope=PolicyScope(
            regions=["全国"],
            industries=industries,
            target_entities=["相关行业、项目单位与实施主体"],
            evidence=[EvidenceQuote(excerpt=title, source_url=source_url)],
            confidence=0.62,
        ),
        impacts=[impact],
        keywords=_infer_keywords(title),
        quality_warnings=["索引样本：文号、正文条款和效力状态仍需详情页核验"],
    )


def _seed_documents() -> list[PolicyDocument]:
    return [
        _seed_document(
            policy_id="policy-ai-plus-state",
            title="国务院关于深入实施“人工智能+”行动的意见",
            publish_date=date(2025, 8, 26),
            source_url="https://www.gov.cn/zhengce/content/202508/content_7037862.htm",
            authorities=["国务院"],
            level=AuthorityLevel.STATE_COUNCIL,
            document_type=PolicyDocumentType.OPINION,
            industries=["人工智能"],
            summary="国务院层面的人工智能应用总体部署，是相关部委实施文件的上位依据。",
        ),
        _seed_document(
            policy_id="policy-ai-telecom",
            title="工业和信息化部关于印发《“人工智能+信息通信”创新发展实施意见（2026—2028年）》的通知",
            publish_date=date(2026, 6, 10),
            source_url="https://www.gov.cn/zhengce/zhengceku/202606/content_7071755.htm",
            authorities=["工业和信息化部"],
            level=AuthorityLevel.MINISTRY,
            document_type=PolicyDocumentType.OPINION,
            industries=["人工智能"],
            summary="面向信息通信行业的人工智能应用实施文件。",
        ),
        _seed_document(
            policy_id="policy-energy-system",
            title="国家发展改革委 国家能源局关于印发《新型能源体系建设“十五五”规划》的通知",
            publish_date=date(2026, 7, 3),
            source_url="https://www.gov.cn/zhengce/zhengceku/202607/content_7074220.htm",
            authorities=["国家发展改革委", "国家能源局"],
            level=AuthorityLevel.MINISTRY,
            document_type=PolicyDocumentType.PLAN,
            industries=["新能源", "电力", "储能"],
            summary="新型能源体系建设的综合性规划索引记录。",
        ),
        _seed_document(
            policy_id="policy-power-system",
            title="国家发展改革委 国家能源局关于印发《新型电力系统建设“十五五”规划》的通知",
            publish_date=date(2026, 8, 3),
            source_url="https://www.gov.cn/zhengce/zhengceku/202608/content_7077425.htm",
            authorities=["国家发展改革委", "国家能源局"],
            level=AuthorityLevel.MINISTRY,
            document_type=PolicyDocumentType.PLAN,
            industries=["电力", "新能源", "储能"],
            summary="聚焦电源、电网、储能与用户侧协同的新型电力系统规划索引记录。",
        ),
        _seed_document(
            policy_id="policy-renewable-plan",
            title="关于印发《可再生能源发展“十五五”规划》的通知",
            publish_date=date(2026, 7, 23),
            source_url="https://www.gov.cn/zhengce/zhengceku/202607/content_7076403.htm",
            authorities=["相关中央部门"],
            level=AuthorityLevel.MINISTRY,
            document_type=PolicyDocumentType.PLAN,
            industries=["新能源", "电力"],
            summary="可再生能源开发、利用和消纳方向的专项规划索引记录。",
        ),
        _seed_document(
            policy_id="policy-green-industry",
            title="工业和信息化部关于印发《工业绿色低碳发展“十五五”规划》的通知",
            publish_date=date(2026, 7, 31),
            source_url="https://www.gov.cn/zhengce/zhengceku/202607/content_7077146.htm",
            authorities=["工业和信息化部"],
            level=AuthorityLevel.MINISTRY,
            document_type=PolicyDocumentType.PLAN,
            industries=["绿色低碳"],
            summary="工业领域绿色制造、节能降碳和技术改造方向的规划索引记录。",
        ),
        *_verified_storage_documents(),
    ]


def _verified_storage_documents() -> list[PolicyDocument]:
    national_url = "https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=19520"
    national_title = "国家发展改革委 国家能源局关于加快推动新型储能发展的指导意见"
    national = PolicyDocument(
        id="policy-storage-guidance-national",
        title=national_title,
        document_number="发改能源规〔2021〕1051号",
        issuing_authorities=["国家发展改革委", "国家能源局"],
        authority_level=AuthorityLevel.MINISTRY,
        document_type=PolicyDocumentType.OPINION,
        lifecycle_status=PolicyLifecycleStatus.EFFECTIVE,
        publish_date=date(2021, 7, 19),
        source_name="国家发展改革委政府信息公开",
        source_url=national_url,
        authenticity_grade=AuthenticityGrade.A,
        is_red_head=True,
        summary="国家层面的新型储能发展指导文件，明确市场机制、技术创新、项目管理和安全监管方向。",
        scope=PolicyScope(
            regions=["全国"],
            industries=["储能", "新能源", "电力"],
            target_entities=["地方发展改革与能源主管部门", "储能企业", "电力企业", "项目单位"],
            project_stages=["研发", "建设", "并网", "运营", "安全监管"],
            evidence=[
                EvidenceQuote(
                    excerpt="鼓励结合源、网、荷不同需求探索储能多元化发展模式。",
                    clause_ref="总体要求",
                    source_url=national_url,
                )
            ],
            confidence=0.96,
        ),
        impacts=[
            PolicyImpact(
                id="impact-storage-guidance-national",
                title="推动新型储能规模化与市场化发展",
                direction="support",
                action="鼓励发展与机制建设",
                target="新型储能技术、项目和市场主体",
                summary="推动价格、市场交易、技术创新、标准检测和安全监管机制协同建设。",
                industries=["储能", "新能源", "电力"],
                chain_nodes=["储能材料", "储能电池", "系统集成", "项目建设", "电力交易"],
                evidence=[
                    EvidenceQuote(
                        excerpt="将发展新型储能作为提升能源电力系统调节能力、综合效率和安全保障能力的重要举措。",
                        clause_ref="指导思想",
                        source_url=national_url,
                    )
                ],
                confidence=0.94,
                review_status="reviewed",
            )
        ],
        keywords=["新型储能", "电力系统", "市场机制", "安全监管"],
    )

    guangdong_url = "https://www.gd.gov.cn/attachment/0/516/516894/4144112.pdf"
    guangdong_title = "广东省人民政府办公厅关于印发广东省推动新型储能产业高质量发展指导意见的通知"
    guangdong = PolicyDocument(
        id="policy-storage-guangdong",
        title=guangdong_title,
        document_number="粤府办〔2023〕4号",
        issuing_authorities=["广东省人民政府办公厅"],
        authority_level=AuthorityLevel.PROVINCE,
        document_type=PolicyDocumentType.OPINION,
        lifecycle_status=PolicyLifecycleStatus.UNKNOWN,
        publish_date=date(2023, 3, 20),
        source_name="广东省人民政府公报",
        source_url=guangdong_url,
        authenticity_grade=AuthenticityGrade.A,
        is_red_head=True,
        summary="围绕技术装备研发、产业布局、应用示范、质量安全和产业环境部署广东省新型储能产业发展。",
        scope=PolicyScope(
            regions=["广东省"],
            industries=["储能", "新能源", "电力"],
            target_entities=["储能企业", "科研机构", "项目单位", "省市主管部门"],
            project_stages=["研发", "制造", "示范应用", "建设运营", "回收利用"],
            evidence=[
                EvidenceQuote(
                    excerpt="将广东打造成为具有全球竞争力的新型储能产业创新高地。",
                    clause_ref="总体要求",
                    source_url=guangdong_url,
                )
            ],
            confidence=0.94,
        ),
        impacts=[
            PolicyImpact(
                id="impact-storage-guangdong",
                title="广东新型储能全产业链培育",
                direction="support",
                action="产业培育与示范应用",
                target="关键材料、核心装备、储能系统及应用项目",
                summary="加强锂离子、钠离子、氢储能、能源电子和全过程安全技术，推动产业链规模化发展。",
                industries=["储能", "新能源", "电力"],
                chain_nodes=["正负极材料", "电芯", "BMS/PCS", "系统集成", "虚拟电厂", "回收利用"],
                evidence=[
                    EvidenceQuote(
                        excerpt="推动创新链、产业链、资金链、人才链深度融合。",
                        clause_ref="总体要求",
                        source_url=guangdong_url,
                    )
                ],
                confidence=0.92,
                review_status="reviewed",
            )
        ],
        keywords=["广东", "新型储能", "锂离子电池", "钠离子电池", "虚拟电厂"],
    )

    shenzhen_url = "https://fgw.sz.gov.cn/gkmlpt/content/10/10415/post_10415166.html"
    shenzhen_title = "深圳市支持电化学储能产业加快发展的若干措施"
    shenzhen = PolicyDocument(
        id="policy-storage-shenzhen",
        title=shenzhen_title,
        document_number="深发改〔2023〕82号",
        issuing_authorities=["深圳市发展和改革委员会"],
        authority_level=AuthorityLevel.CITY,
        document_type=PolicyDocumentType.MEASURE,
        lifecycle_status=PolicyLifecycleStatus.EXPIRED,
        publish_date=date(2023, 2, 7),
        effective_date=date(2023, 2, 7),
        expiry_date=date(2026, 2, 6),
        source_name="深圳市发展和改革委员会",
        source_url=shenzhen_url,
        authenticity_grade=AuthenticityGrade.A,
        summary="从产业生态、创新能力、先进制造、应用场景、国际市场和金融服务等方面支持深圳电化学储能产业。",
        scope=PolicyScope(
            regions=["深圳市"],
            industries=["储能", "新能源"],
            target_entities=["企业", "事业单位", "社会团体", "民办非企业"],
            project_stages=["研发", "生产", "建设运营", "市场服务", "回收利用"],
            conditions=["在深圳登记注册", "具备独立法人资格", "从事电化学储能研发、生产或服务"],
            valid_from=date(2023, 2, 7),
            valid_until=date(2026, 2, 6),
            evidence=[
                EvidenceQuote(
                    excerpt="本措施适用于已登记注册，具备独立法人资格，从事电化学储能研发、生产和服务的企业以及其他事业单位、社会团体、民办非企业等机构。",
                    clause_ref="一、重点支持机构和领域",
                    source_url=shenzhen_url,
                )
            ],
            confidence=0.98,
        ),
        impacts=[
            PolicyImpact(
                id="impact-storage-shenzhen",
                title="深圳电化学储能全链条支持",
                direction="support",
                action="贴息、奖励、平台建设和应用示范",
                target="电化学储能产业链及符合条件的深圳主体",
                summary="覆盖原材料、元器件、工艺装备、电芯模组、BMS/EMS、系统集成、运营服务和电池回收利用。",
                industries=["储能", "新能源"],
                chain_nodes=["原材料", "电芯模组", "BMS/EMS", "系统集成", "项目运营", "电池回收"],
                evidence=[
                    EvidenceQuote(
                        excerpt="本措施重点支持面向先进电化学储能技术路线的原材料、元器件、工艺装备、电芯模组、电池管理系统、能量管理系统、变流器、系统集成、建设运营、市场服务、电池回收与综合利用等重点领域链条。",
                        clause_ref="一、重点支持机构和领域",
                        source_url=shenzhen_url,
                    )
                ],
                confidence=0.98,
                review_status="reviewed",
            )
        ],
        keywords=["深圳", "电化学储能", "电芯模组", "系统集成", "电池回收"],
        quality_warnings=["该措施原定有效期三年，当前已超过原有效期，应核验是否存在续期或替代文件。"],
    )
    return [national, guangdong, shenzhen]


def _seed_relations() -> list[PolicyRelation]:
    return [
        PolicyRelation(
            source_id="policy-ai-telecom",
            target_id="policy-ai-plus-state",
            relation="implements",
            confidence=0.78,
            evidence="部委实施意见与国务院“人工智能+”总体部署形成上下位实施关系，待正文引用核验。",
        ),
        PolicyRelation(
            source_id="policy-power-system",
            target_id="policy-energy-system",
            relation="implements",
            confidence=0.72,
            evidence="新型电力系统规划属于新型能源体系建设的专项落地关系，待正文引用核验。",
        ),
        PolicyRelation(
            source_id="policy-renewable-plan",
            target_id="policy-energy-system",
            relation="implements",
            confidence=0.7,
            evidence="可再生能源规划与综合能源体系规划形成专项实施关系，待正文引用核验。",
        ),
        PolicyRelation(
            source_id="policy-green-industry",
            target_id="policy-energy-system",
            relation="overlaps",
            confidence=0.58,
            evidence="两份规划在工业节能降碳与能源转型范围存在交集。",
        ),
        PolicyRelation(
            source_id="policy-energy-system",
            target_id="policy-storage-guidance-national",
            relation="based_on",
            confidence=0.65,
            evidence="综合能源体系规划与既有新型储能指导政策形成延续关系，待正文引用核验。",
        ),
        PolicyRelation(
            source_id="policy-storage-guangdong",
            target_id="policy-storage-guidance-national",
            relation="localizes",
            confidence=0.97,
            evidence="广东省指导意见正文明确依据国家发展改革委、国家能源局新型储能指导意见。",
        ),
        PolicyRelation(
            source_id="policy-storage-shenzhen",
            target_id="policy-storage-guidance-national",
            relation="localizes",
            confidence=0.72,
            evidence="深圳措施将国家新型储能发展方向细化到本地电化学储能产业链，直接引用关系待进一步核验。",
        ),
    ]
