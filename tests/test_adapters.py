"""Offline checks of both memory adapters against fake platform clients.

  python tests/test_adapters.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "shared"),
    str(ROOT / "side_a_agentcore" / "app" / "card_agent"),
    str(ROOT / "side_b_atlas" / "agents" / "card-agent"),
]
os.environ.setdefault("AGENTCORE_MEMORY_ID", "mem-test")
os.environ.setdefault("AWS_REGION", "us-east-1")


# ---------- Side A ----------
class FakeAgentCore:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self):
        self.records = {
            "/bakeoff/facts/C-1001/": [
                {"memoryRecordId": "r1", "score": 0.9, "content": {"text": "Pre-qualified for SGD 25,000."},
                 "metadata": {"label": {"stringValue": "credit-limit-offer"}, "kind": {"stringValue": "offer"}}},
            ],
            "/facts/C-1001/": [
                {"memoryRecordId": "r2", "score": 0.8, "content": {"text": "pre-qualified for  SGD 25,000."}},  # dup
                {"memoryRecordId": "r3", "score": 0.7, "content": {"text": "Moving to Melbourne next month."}},
            ],
            "/preferences/C-1001/": [{"memoryRecordId": "r4", "score": 0.6, "content": {"text": "Prefers email."}}],
            "/bakeoff/procedures/": [{"memoryRecordId": "p1", "score": 0.9, "content": {"text": "late-fee-waiver: steps"}}],
            "/bakeoff/glossary/cards/": [{"memoryRecordId": "g1", "score": 0.9, "content": {"text": "provisional credit: temp"}}],
        }
        self.deleted, self.created = [], []

    def retrieve_memory_records(self, memoryId, namespace, searchCriteria, maxResults):
        assert memoryId == "mem-test" and searchCriteria["topK"] == maxResults
        return {"memoryRecordSummaries": self.records.get(namespace, [])[:maxResults]}

    def list_memory_records(self, memoryId, namespace, maxResults, nextToken=None):
        return {"memoryRecordSummaries": self.records.get(namespace, [])}

    def batch_delete_memory_records(self, memoryId, records):
        self.deleted += records
        return {"successfulRecords": records, "failedRecords": []}

    def batch_create_memory_records(self, memoryId, records):
        self.created += records
        return {"successfulRecords": [{"memoryRecordId": "new1", "status": "SUCCEEDED"}], "failedRecords": []}


def test_side_a() -> None:
    from memory_agentcore import AgentCoreMemory

    mem = AgentCoreMemory(region="us-east-1")
    mem.client = FakeAgentCore()

    ctx = mem.context("C-1001", "limit increase")
    assert ctx.text.count("25,000") == 1, "duplicates must be removed"
    assert "Melbourne" in ctx.text and ctx.sources == {"custom_facts": 1, "facts": 1, "preferences": 1}, ctx.sources

    small = AgentCoreMemory(region="us-east-1", max_context_tokens=10)
    small.client = FakeAgentCore()
    assert small.context("C-1001", "x").text.count("\n") == 0, "budget must trim"

    ref = mem.remember("C-1001", "credit-limit-offer", "WITHDRAWN", kind="offer")
    assert ref == "new1" and mem.client.deleted[0]["memoryRecordId"] == "r1", "same label replaced"
    assert mem.find_procedure("waiver").startswith("late-fee-waiver")
    assert mem.define_term("provisional credit").startswith("provisional credit")
    print("Side A adapter OK:", ctx.notes[0])


# ---------- Side B ----------
class FakeAtlasMemory:
    def __init__(self):
        self.calls = []

    def build_context(self, **kw):
        self.calls.append(("build_context", kw))
        return SimpleNamespace(formatted_context="<memories>pre-qualified</memories>",
                               metadata=SimpleNamespace(token_count=42))

    def save_semantic(self, **kw):
        self.calls.append(("save_semantic", kw))
        return SimpleNamespace(id="m1")

    def discover_procedures(self, query, **kw):
        return [{"procedure": "late-fee-waiver", "description": "d"}]

    def get_procedure(self, name, **kw):
        return SimpleNamespace(content="1. check 2. waive")

    def search_taxonomic(self, query, **kw):
        assert kw["visibility"] == "org" and kw["domain"] == "cards"
        return [SimpleNamespace(content="provisional credit: temporary credit")]


def test_side_b() -> None:
    from card_agent.memory_atlas import AtlasMemory

    fake = FakeAtlasMemory()
    mem = AtlasMemory(lambda: fake, max_context_tokens=1500)
    ctx = mem.context("C-1001", "limit")
    assert ctx.token_estimate == 42 and "pre-qualified" in ctx.text
    kw = fake.calls[0][1]
    assert kw["user_id"] == "C-1001" and kw["max_tokens"] == 2000 and kw["enabled_sources"] == {"semantic", "episodic"}
    assert mem.remember("C-1001", "x", "y") == "m1" and fake.calls[1][1]["upsert"] is True
    assert mem.find_procedure("waiver") == "late-fee-waiver: 1. check 2. waive"
    assert "temporary" in mem.define_term("provisional credit")

    # app-bound build_context may return a plain string
    fake.build_context = lambda **kw: "plain string context"
    assert mem.context("C-1001", "q").text == "plain string context"
    print("Side B adapter OK")


if __name__ == "__main__":
    test_side_a()
    test_side_b()
    print("OK: both memory adapters behave as expected against fakes")
