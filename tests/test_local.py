"""Local check of the shared agent with no cloud access.

A scripted fake model plays the fee-waiver scene, using in-memory BankData and
AgentMemory. Proves the graph wiring, tools, state shape and checkpointing.

  pip install langgraph langchain-core
  python tests/test_local.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool as lc_tool  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

from bakeoff import MemoryContext, build_graph, final_text, make_tool_functions, turn_tool_calls  # noqa: E402

SEED = json.loads((ROOT / "data" / "seed.json").read_text())


class FakeBank:
    def __init__(self):
        self.accounts = {a["customer_id"]: dict(a) for a in SEED["accounts"]}
        self.customers = {c["customer_id"]: c for c in SEED["customers"]}
        self.waivers: list[dict] = []

    def get_account(self, cid): return self.accounts.get(cid)
    def get_customer(self, cid): return self.customers.get(cid)
    def last_fee_waiver(self, cid): return next((w for w in reversed(self.waivers) if w["customer_id"] == cid), None)

    def record_fee_waiver(self, cid, amount, code):
        w = {"customer_id": cid, "amount_sgd": amount, "reason_code": code, "waived_on": date.today().isoformat()}
        self.waivers.append(w)
        self.accounts[cid]["late_fee_sgd"] = 0
        return {"waived": True, **w}

    def request_limit_increase(self, cid, new_limit):
        if self.accounts[cid]["status"] != "active":
            return {"accepted": False, "reason": "blocked: refer to specialist"}
        return {"accepted": True, "requested_limit_sgd": new_limit}

    def get_open_dispute(self, cid): return SEED["disputes"][0]


class FakeMemory:
    def __init__(self):
        self.facts = {SEED["memories"]["offer"]["label"]: SEED["memories"]["offer"]["text"]}

    def context(self, cid, query, session_id=None):
        text = "\n".join(f"- {t}" for t in self.facts.values())
        return MemoryContext(text=text, token_estimate=len(text) // 4, sources={"fake": len(self.facts)})

    def remember(self, cid, label, text, kind="fact"):
        self.facts[label] = text
        return label

    def find_procedure(self, task):
        p = SEED["procedures"][0]
        return f"{p['procedure']}: {p['content']}"

    def define_term(self, term):
        return SEED["glossary"][0]["definition"]


class ScriptedModel:
    """Plays the fee-waiver procedure: find_procedure -> eligibility -> waiver -> reply."""

    def __init__(self):
        self.seen_prompts: list[str] = []

    def bind_tools(self, _tools):
        return self

    def invoke(self, messages):
        self.seen_prompts.append(messages[0].content)
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        n = len(tool_results)
        if n == 0:
            return AIMessage(content="", tool_calls=[{"name": "find_procedure", "args": {"task": "late fee waiver"}, "id": "t1"}])
        if n == 1:
            return AIMessage(content="", tool_calls=[{"name": "check_fee_waiver_eligibility", "args": {"customer_id": "C-1001"}, "id": "t2"}])
        if n == 2:
            elig = json.loads(tool_results[-1].content)
            assert elig["tenure_months"] >= 12 and elig["overdue_paid"], elig
            return AIMessage(content="", tool_calls=[{"name": "apply_fee_waiver", "args": {"customer_id": "C-1001", "reason_code": "LFW-01"}, "id": "t3"}])
        return AIMessage(content="Done. I've waived the SGD 100 late fee. This uses your one waiver for the next 12 months.")


def main() -> None:
    bank, memory, model = FakeBank(), FakeMemory(), ScriptedModel()
    tools = [lc_tool(fn) for fn in make_tool_functions(bank, memory)]
    graph = build_graph(model.bind_tools(tools), ToolNode(tools), memory, MemorySaver())

    cfg = {"configurable": {"thread_id": "local-test"}}
    result = graph.invoke({"messages": [HumanMessage(content="Can you waive the late fee?")], "customer_id": "C-1001"}, cfg)

    calls = turn_tool_calls(result)
    assert calls == ["find_procedure", "check_fee_waiver_eligibility", "apply_fee_waiver"], calls
    assert bank.accounts["C-1001"]["late_fee_sgd"] == 0
    assert "pre-qualified" in model.seen_prompts[0], "memory context must reach the system prompt"
    assert result["memory_tokens"] > 0 and result["customer_id"] == "C-1001"
    json.dumps({k: v for k, v in result.items() if k != "messages"})  # state must be JSON-serializable

    # Second turn on the same thread: only this turn's tool calls are reported.
    model2_turn = graph.invoke({"messages": [HumanMessage(content="Thanks!")], "customer_id": "C-1001"}, cfg)
    assert len([m for m in model2_turn["messages"] if isinstance(m, HumanMessage)]) == 2

    print("Reply:", final_text(result))
    print("Tool calls:", calls)
    print("Memory tokens in prompt:", result["memory_tokens"])
    print("OK: shared agent graph works end to end with fake model, bank and memory")


if __name__ == "__main__":
    main()
