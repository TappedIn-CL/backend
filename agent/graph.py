from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.nodes import parse_intent, retrieve_events, score_and_rank
from agent.scoring import compute_taste


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("parse_intent", parse_intent)
    graph.add_node("retrieve_events", retrieve_events)
    graph.add_node("compute_taste", compute_taste)
    graph.add_node("score_and_rank", score_and_rank)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "retrieve_events")
    graph.add_edge("retrieve_events", "compute_taste")
    graph.add_edge("compute_taste", "score_and_rank")
    graph.add_edge("score_and_rank", END)

    return graph.compile()


agent = build_graph()
