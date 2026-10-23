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
from pydantic import SecretStr

from bakeoff import DEFAULT_CUSTOMER_ID, DEFAULT_MODEL, build_graph, make_tool_functions
from card_agent.bank_atlas import AtlasBank
from card_agent.memory_atlas import AtlasMemory, HostedMemory

log = logging.getLogger("card_agent")
MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

app = App(app_name="card-agent")
bank = AtlasBank()
# Per-customer memory needs the service-account client (see HostedMemory); without
# AE_CLIENT_ID/AE_CLIENT_SECRET secrets, fall back to app.memory (caller identity only).
_hosted = HostedMemory.from_env()
if _hosted is None:
    log.warning("AE_CLIENT_ID/AE_CLIENT_SECRET not set: per-customer memory calls will get 403 via app.memory")
memory = AtlasMemory(_hosted or (lambda: app.memory))

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


def _anthropic_key() -> SecretStr:
    # Agent Engine scaffolds name the model secret LLM_API_KEY; ANTHROPIC_API_KEY works for local runs.
    key = os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No Anthropic key: agentengine secret set LLM_API_KEY")
    return SecretStr(key)


@app.entrypoint
def build_agent():
    # No temperature: claude-sonnet-5-5 rejects non-default values. Keep this identical to Side A.
    llm = app.llm(ChatAnthropic(model=MODEL, api_key=_anthropic_key(), max_tokens=1024))
    llm_with_tools = llm.bind_tools(app.get_tool_schemas())
    return build_graph(llm_with_tools, ToolNode(app.get_tools()), memory, app.checkpointer())


def main() -> None:
    # The platform imports `app` (agent.yaml entrypoint) and calls app.run() itself.
    app.run()


if __name__ == "__main__":
    main()
