"""The one LangGraph agent both platforms run.

    START -> recall -> agent <-> tools -> END

recall  reads agent memory for the latest customer message (platform-specific adapter)
agent   calls the model with the shared system prompt + remembered context
tools   runs the shared tools

Graph state stays JSON-serializable, which Atlas Agent Engine requires for checkpoints.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .ports import AgentMemory
from .prompts import system_prompt

DEFAULT_CUSTOMER_ID = "C-1001"


class CardAgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: str
    session_id: str
    memory_context: str
    memory_tokens: int
    memory_sources: dict[str, int]


def _last_user_text(messages: list[AnyMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            content = msg.content
            if isinstance(content, list):  # content blocks
                return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)
    return ""


def build_graph(llm_with_tools: Any, tool_node: Any, memory: AgentMemory, checkpointer: Any = None):
    """llm_with_tools: a chat model already bound to the tool schemas.
    tool_node: a LangGraph ToolNode (or platform-wrapped equivalent)."""

    def recall(state: CardAgentState) -> dict[str, Any]:
        customer_id = state.get("customer_id") or DEFAULT_CUSTOMER_ID
        query = _last_user_text(state.get("messages", []))
        ctx = memory.context(customer_id, query, session_id=state.get("session_id"))
        return {
            "customer_id": customer_id,
            "memory_context": ctx.text,
            "memory_tokens": ctx.token_estimate,
            "memory_sources": ctx.sources,
        }

    def agent(state: CardAgentState) -> dict[str, Any]:
        prompt = system_prompt(state.get("customer_id") or DEFAULT_CUSTOMER_ID, state.get("memory_context", ""))
        # The system message is built per call and never stored in state,
        # so checkpoints don't accumulate one system message per turn.
        response = llm_with_tools.invoke([SystemMessage(content=prompt), *state["messages"]])
        return {"messages": [response]}

    def route(state: CardAgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(CardAgentState)
    graph.add_node("recall", recall)
    graph.add_node("agent", agent)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "recall")
    graph.add_edge("recall", "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def turn_tool_calls(result: dict[str, Any]) -> list[str]:
    """Names of tools called in the latest turn only (the checkpoint holds earlier turns too)."""
    messages = result["messages"]
    start = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            start = i
    return [tc["name"] for m in messages[start:] for tc in (getattr(m, "tool_calls", None) or [])]


def final_text(result: dict[str, Any]) -> str:
    """Extract the agent's last reply as plain text."""
    msg = result["messages"][-1]
    content = msg.content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return str(content)
