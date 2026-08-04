from langgraph.graph import END, START, StateGraph

from agent.llm import OptionalPolicyLLM
from agent.nodes import build_nodes, route_evidence, route_match
from agent.state import AnalysisState
from src.services.rag_service import GraphRAGService


def build_analysis_graph(rag: GraphRAGService, llm: OptionalPolicyLLM):
    nodes = build_nodes(rag, llm)
    graph = StateGraph(AnalysisState)
    for name, node in nodes.items():
        graph.add_node(name, node)

    # 链路解构：政策 → 产业 → 供应链 → 公司。没匹配到公司时回退到 broaden_match 循环放宽重试。
    graph.add_edge(START, "extract_policy")
    graph.add_edge("extract_policy", "expand_chain")
    graph.add_edge("expand_chain", "match_companies")
    graph.add_conditional_edges(
        "match_companies",
        route_match,
        {"broaden_match": "broaden_match", "form_candidate": "form_candidate"},
    )
    graph.add_conditional_edges(
        "broaden_match",
        route_match,
        {"broaden_match": "broaden_match", "form_candidate": "form_candidate"},
    )

    # 候选生成 → 证据检索：证据不足时循环放宽检索关键词。
    graph.add_edge("form_candidate", "gather_evidence")
    graph.add_conditional_edges(
        "gather_evidence",
        route_evidence,
        {"broaden_evidence": "broaden_evidence", "adversarial_check": "adversarial_check"},
    )
    graph.add_edge("broaden_evidence", "gather_evidence")

    # 对抗式核验 → 图谱装配。
    graph.add_edge("adversarial_check", "assemble_graph")
    graph.add_edge("assemble_graph", END)
    return graph.compile()
