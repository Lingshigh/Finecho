import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

from src.models.schemas import Evidence


def _tokens(text: str) -> set[str]:
    latin = set(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
    chinese = re.findall(r"[一-鿿]", text)
    bigrams = {"".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1))}
    return latin | bigrams


class GraphRAGService:
    """GraphRAG adapter：图遍历负责候选召回（find_companies），TF-IDF 余弦负责证据排序（retrieve）。

    图结构：industry --contains--> company --produces--> product。
    检索时把查询词映射到图中节点做 BFS，再以图路径距离作为相关度因子；
    证据排序用 TF-IDF 余弦绝对分数（不做 min-max 归一化，保证跨公司可比），替代原字符重叠词袋。
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.companies: list[dict[str, Any]] = self._load("companies.json")
        # 追加 AKShare 动态行业公司（文件缺失时静默跳过，保持仅演示公司池可运行）。
        self.companies.extend(self._load_optional("companies.dynamic.json"))
        self.documents: list[dict[str, Any]] = self._load("evidence.json")
        self.graph = nx.MultiDiGraph()
        self._build_graph()
        # 查询词 → 图节点 id 的映射（子串匹配，用于把 policy 关键词落到图上）。
        self._term_to_node: dict[str, str] = {}
        self._index_terms()
        # TF-IDF 索引：idf 向量、每篇文档的词频向量。
        self._idf: dict[str, float] = {}
        self._doc_vectors: dict[str, dict[str, float]] = {}
        self._build_tfidf()

    def _load(self, name: str) -> list[dict[str, Any]]:
        with (self.data_dir / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_optional(self, name: str) -> list[dict[str, Any]]:
        """加载可选数据文件；文件缺失或格式非法时返回空列表，不抛错。"""
        path = self.data_dir / name
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, list) else []
        except (OSError, ValueError):
            return []

    def _build_graph(self) -> None:
        for company in self.companies:
            self.graph.add_node(company["id"], kind="company", **company)
            for industry in company["industries"]:
                industry_id = f"industry:{industry}"
                self.graph.add_node(industry_id, kind="industry", label=industry)
                self.graph.add_edge(industry_id, company["id"], relation="contains")
            for product in company["products"]:
                product_id = f"product:{product}"
                self.graph.add_node(product_id, kind="product", label=product)
                self.graph.add_edge(company["id"], product_id, relation="produces")

    def _index_terms(self) -> None:
        for node_id, attrs in self.graph.nodes(data=True):
            label = attrs.get("label") or node_id.split(":", 1)[-1]
            self._term_to_node[label] = node_id

    def _resolve_start_nodes(self, terms: list[str]) -> list[str]:
        """把查询词映射到图节点 id：先精确命中 label，再子串兜底（须确保节点存在于图中）。"""
        resolved: list[str] = []
        seen: set[str] = set()
        for term in terms:
            node = self._term_to_node.get(term)
            if node is None:
                node = next(
                    (nid for nid in self._term_to_node if term in nid or nid in term),
                    None,
                )
            if node and node not in seen and self.graph.has_node(node):
                seen.add(node)
                resolved.append(node)
        return resolved

    def find_companies(
        self, industries: list[str], products: list[str], targets: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """图遍历召回候选公司：从查询词落图节点出发做 BFS，路径越近相关度越高。"""
        target_set = {value.lower() for value in (targets or [])}
        if target_set:
            # 显式指定目标时，直接从目标公司出发按暴露度排序。
            return [
                company
                for company in self.companies
                if company["id"].lower() in target_set or company["name"].lower() in target_set
            ]

        start_nodes = self._resolve_start_nodes([*industries, *products])
        if not start_nodes:
            return []

        # 无向 BFS：industry --contains--> company --produces--> product 视为可双向遍历，
        # 用「查询词节点 → 公司」的最短路径长度作为相关度距离。
        undirected = self.graph.to_undirected()
        distances: dict[str, int] = {}
        for start in start_nodes:
            for node, dist in nx.single_source_shortest_path_length(
                undirected, start, cutoff=2
            ).items():
                if self.graph.nodes[node].get("kind") == "company" and (
                    node not in distances or dist < distances[node]
                ):
                    distances[node] = dist

        ranked: list[tuple[float, dict[str, Any]]] = []
        for company_id, dist in distances.items():
            company = self.graph.nodes[company_id]
            # 图距离越近分越高：dist=1（industry 直达）给满分，dist=2（经 product）减半。
            graph_score = 1.0 if dist == 1 else 0.6
            ranked.append(
                (graph_score + company.get("revenue_exposure", 0.0), company)
            )
        return [
            dict(item[1])
            for item in sorted(ranked, key=lambda pair: pair[0], reverse=True)
        ]

    def _build_tfidf(self) -> None:
        doc_count = len(self.documents)
        doc_freq: dict[str, int] = defaultdict(int)
        for document in self.documents:
            text = " ".join([document["title"], document["excerpt"], *document["keywords"]])
            for token in _tokens(text):
                doc_freq[token] += 1
        self._idf = {
            token: math.log(1 + doc_count / (1 + freq)) for token, freq in doc_freq.items()
        }
        for document in self.documents:
            self._doc_vectors[document["id"]] = self._vectorize(
                " ".join([document["title"], document["excerpt"], *document["keywords"]])
            )

    def _vectorize(self, text: str) -> dict[str, float]:
        counts: dict[str, int] = defaultdict(int)
        for token in _tokens(text):
            counts[token] += 1
        norm = math.sqrt(sum((count * self._idf.get(token, 0.0)) ** 2 for token, count in counts.items()))
        if norm == 0:
            return {}
        return {
            token: count * self._idf.get(token, 0.0) / norm
            for token, count in counts.items()
        }

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        shared = set(a) & set(b)
        if not shared:
            return 0.0
        return sum(a[token] * b[token] for token in shared)

    def retrieve(self, company_id: str, query: str, limit: int = 3) -> list[Evidence]:
        query_vector = self._vectorize(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for document in self.documents:
            if document["company_id"] != company_id:
                continue
            relevance = self._cosine(query_vector, self._doc_vectors.get(document["id"], {}))
            if relevance > 0:
                ranked.append((relevance, document))
        # 按绝对 TF-IDF 余弦排序取 top，不做 min-max 归一化：
        # 归一化会让每家 top 证据恒为 1.0，抹平"这家到底多相关"的跨公司判别力。
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [
            Evidence(
                id=document["id"],
                company_id=document["company_id"],
                source_type=document["source_type"],
                title=document["title"],
                excerpt=document["excerpt"],
                year=document.get("year"),
                source_url=document.get("source_url"),
                relevance=round(score, 3),
            )
            for score, document in ranked[:limit]
        ]
