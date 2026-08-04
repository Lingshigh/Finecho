from langgraph.graph import END, START, StateGraph

from agent.llm import OptionalPolicyLLM
from agent.nodes import build_nodes
from agent.state import AnalysisState
from src.services.rag_service import GraphRAGService


def build_analysis_graph(rag: GraphRAGService, llm: OptionalPolicyLLM):
    nodes = build_nodes(rag, llm)
    graph = StateGraph(AnalysisState)
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "extract_policy")
    graph.add_edge("extract_policy", "expand_chain")
    graph.add_edge("expand_chain", "match_companies")
    graph.add_edge("match_companies", "verify_companies")
    graph.add_edge("verify_companies", "assemble_graph")
    graph.add_edge("assemble_graph", END)
    return graph.compile()
