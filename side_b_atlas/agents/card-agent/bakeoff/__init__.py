"""Shared card servicing agent for the AgentCore vs Atlas Agent Engine bake-off.

This package is copied into both deployable agents by scripts/sync_shared.sh.
Edit it here, never in the copies.
"""
from .graph import DEFAULT_CUSTOMER_ID, CardAgentState, build_graph, final_text, turn_tool_calls
from .ports import AgentMemory, BankData, MemoryContext, estimate_tokens
from .tools import make_tool_functions

__all__ = [
    "AgentMemory",
    "BankData",
    "CardAgentState",
    "DEFAULT_CUSTOMER_ID",
    "MemoryContext",
    "build_graph",
    "estimate_tokens",
    "final_text",
    "make_tool_functions",
    "turn_tool_calls",
]

DEFAULT_MODEL = "claude-sonnet-5-5"
