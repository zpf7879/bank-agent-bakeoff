"""Side B entrypoint: the same LangGraph card agent on MongoDB Atlas Agent Engine.

Invoke:
  POST .../workspaces/{workspace_id}/invoke   {"message": "...", "customer_id": "C-1001"}
  optional header X-Mdb-Agent-Engine-Custom-Customer-Id: C-1001
"""
from __future__ import annotations

import logging
import os
from typing import Any

from agent_engine_sdk_langgraph import App
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode

from bakeoff import DEFAULT_CUSTOMER_ID, DEFAULT_MODEL, build_graph, make_tool_functions
from card_agent.bank_atlas import AtlasBank
from card_agent.memory_atlas import AtlasMemory

log = logging.getLogger("card_agent")
MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

app = App(app_name="card-agent")
bank = AtlasBank()
memory = AtlasMemory(lambda: app.memory)

# Register the shared tools through the platform wrapper, so every call is
# audited and checked by the policy engine.
for fn in make_tool_functions(bank, memory):
    app.tool()(fn)


def _custom_headers() -> dict[str, str]:
    try:
        from agent_engine_runner_shared import get_current_custom_headers

        return get_current_custom_headers() or {}
    except Exception:
        return {}


@app.prepare_agent_input
def prepare(agent_input: Any, ctx: Any) -> dict[str, Any]:
    payload = getattr(agent_input, "payload", agent_input)
    if not isinstance(payload, dict):
        payload = {"message": str(payload)}
    customer_id = (
        payload.get("customer_id")
        or _custom_headers().get("customer-id")
        or DEFAULT_CUSTOMER_ID
    )
    return {
        "messages": [HumanMessage(content=payload.get("message") or payload.get("prompt") or "")],
        "customer_id": customer_id,
        "session_id": getattr(ctx, "session_id", None) or "",
    }


@app.entrypoint
def build_agent():
    llm = app.llm(ChatAnthropic(model=MODEL, max_tokens=1024, temperature=0))
    llm_with_tools = llm.bind_tools(app.get_tool_schemas())
    return build_graph(llm_with_tools, ToolNode(app.get_tools()), memory, app.checkpointer())


app.run()
