from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.grok_client import get_chat_model


class GraphState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_graph():
    llm = get_chat_model()

    def agent(state: GraphState) -> GraphState:
        msgs = state["messages"]
        reply = llm.invoke(msgs)
        return {"messages": [reply]}

    g = StateGraph(GraphState)
    g.add_node("agent", agent)
    g.add_edge(START, "agent")
    g.add_edge("agent", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_langgraph(prompt: str) -> str:
    graph = get_graph()
    result = graph.invoke({"messages": [HumanMessage(content=prompt)]})
    last = result["messages"][-1]
    if isinstance(last, AIMessage):
        return last.content or ""
    return str(getattr(last, "content", last))
