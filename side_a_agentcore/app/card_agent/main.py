"""Side A entrypoint: LangGraph card agent on Amazon Bedrock AgentCore Runtime.

Invoke payload:
  {"prompt": "...", "customer_id": "C-1001"}
Session continuity comes from the runtime session ID (agentcore invoke --session-id ...).
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as lc_tool
from langgraph.prebuilt import ToolNode
from langgraph_checkpoint_aws import AgentCoreMemorySaver

from bakeoff import DEFAULT_CUSTOMER_ID, DEFAULT_MODEL, build_graph, final_text, make_tool_functions, turn_tool_calls
from bank_aurora import AuroraBank
from memory_agentcore import AgentCoreMemory

log = logging.getLogger("card_agent")
REGION = os.getenv("AWS_REGION", "ap-southeast-1")
MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

app = BedrockAgentCoreApp()
_state: dict = {}


def _anthropic_key() -> str:
    """Same model and provider as Side B: Claude through the Anthropic API.

    Preferred: keep the model loader that `agentcore create --model-provider Anthropic`
    generated and pass its key here. Fallbacks: ANTHROPIC_API_KEY, or an AgentCore
    Identity API-key credential provider named in ANTHROPIC_CREDENTIAL_PROVIDER.
    """
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        return key
    provider = os.getenv("ANTHROPIC_CREDENTIAL_PROVIDER")
    if provider:
        from bedrock_agentcore.identity.auth import requires_api_key

        @requires_api_key(provider_name=provider)
        def _get(*, api_key: str) -> str:
            return api_key

        return _get()
    raise RuntimeError("No Anthropic key: set ANTHROPIC_API_KEY or ANTHROPIC_CREDENTIAL_PROVIDER")


def _setup() -> None:
    if _state:
        return
    memory = AgentCoreMemory(region=REGION)
    bank = AuroraBank()
    tools = [lc_tool(fn) for fn in make_tool_functions(bank, memory)]
    llm = ChatAnthropic(model=MODEL, api_key=_anthropic_key(), max_tokens=1024, temperature=0)
    checkpointer = AgentCoreMemorySaver(memory.memory_id, region_name=REGION)
    _state.update(
        memory=memory,
        graph=build_graph(llm.bind_tools(tools), ToolNode(tools), memory, checkpointer),
    )


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    _setup()
    prompt = payload.get("prompt") or payload.get("message") or ""
    customer_id = payload.get("customer_id") or DEFAULT_CUSTOMER_ID
    session_id = getattr(context, "session_id", None) or payload.get("session_id") or uuid.uuid4().hex * 2

    started = time.perf_counter()
    result = _state["graph"].invoke(
        {"messages": [HumanMessage(content=prompt)], "customer_id": customer_id, "session_id": session_id},
        config={"configurable": {"thread_id": session_id, "actor_id": customer_id}},
    )
    reply = final_text(result)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # Short-term events feed AgentCore's built-in extraction strategies.
    try:
        _state["memory"].record_turn(customer_id, session_id, "USER", prompt)
        _state["memory"].record_turn(customer_id, session_id, "ASSISTANT", reply)
    except Exception:  # memory write must not break the reply
        log.exception("create_event failed")

    tool_calls = turn_tool_calls(result)
    return {
        "result": reply,
        "side": "A-agentcore",
        "elapsed_ms": elapsed_ms,
        "memory_context_tokens": result.get("memory_tokens"),
        "memory_sources": result.get("memory_sources"),
        "tool_calls": tool_calls,
    }


if __name__ == "__main__":
    app.run()
