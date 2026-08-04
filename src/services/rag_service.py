import json
import re
from pathlib import Path
from typing import Any

import networkx as nx

from src.models.schemas import Evidence


def _tokens(text: str) -> set[str]:
    latin = set(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = {"".join(chinese[i : i + 2]) for i in range(max(0, len(chinese) - 1))}
    return latin | bigrams


class GraphRAGService:
    """Small local GraphRAG adapter with a clean upgrade path to ChromaDB."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.companies: list[dict[str, Any]] = self._load("companies.json")
        self.documents: list[dict[str, Any]] = self._load("evidence.json")
        self.graph = nx.MultiDiGraph()
        self._build_graph()

    def _load(self, name: str) -> list[dict[str, Any]]:
        with (self.data_dir / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)

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

    def find_companies(
        self, industries: list[str], products: list[str], targets: list[str] | None = None
    ) -> list[dict[str, Any]]:
        target_set = {value.lower() for value in (targets or [])}
        candidates: list[tuple[float, dict[str, Any]]] = []
        query_terms = set(industries + products)
        for company in self.companies:
            if target_set and not (
                company["id"].lower() in target_set or company["name"].lower() in target_set
            ):
                continue
            own_terms = set(company["industries"] + company["products"])
            overlap = sum(
                1 for query in query_terms for own in own_terms if query in own or own in query
            )
            if overlap or target_set:
                candidates.append((overlap + company["revenue_exposure"], company))
        return [item for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True)]

    def retrieve(self, company_id: str, query: str, limit: int = 3) -> list[Evidence]:
        query_tokens = _tokens(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for document in self.documents:
            if document["company_id"] != company_id:
                continue
            doc_text = " ".join([document["title"], document["excerpt"], *document["keywords"]])
            doc_tokens = _tokens(doc_text)
            overlap = len(query_tokens & doc_tokens)
            relevance = min(1.0, 0.45 + overlap * 0.08)
            ranked.append((relevance, document))
        return [
            Evidence(
                id=document["id"],
                company_id=document["company_id"],
                source_type=document["source_type"],
                title=document["title"],
                excerpt=document["excerpt"],
                year=document.get("year"),
                source_url=document.get("source_url"),
                relevance=score,
            )
            for score, document in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:limit]
        ]
