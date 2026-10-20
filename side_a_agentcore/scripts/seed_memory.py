"""Seed AgentCore Memory for the demo (Side A).

Writes, for customer C-1001:
  - the pre-qualified limit-increase offer (Scene 2)
  - a contact preference
and, shared across customers (custom namespaces you design yourself on Side A):
  - the bank's procedures (Scene 3)
  - the bank's glossary (Scene 4)

Usage:
  python side_a_agentcore/scripts/seed_memory.py [--reset]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "side_a_agentcore" / "app" / "card_agent"), str(ROOT / "shared")]

from memory_agentcore import AgentCoreMemory  # noqa: E402


def records(mem: AgentCoreMemory, namespace: str, items: list[tuple[str, dict[str, str]]]) -> None:
    now = datetime.now(timezone.utc)
    resp = mem.client.batch_create_memory_records(
        memoryId=mem.memory_id,
        records=[
            {
                "requestIdentifier": uuid.uuid4().hex[:16],
                "namespaces": [namespace],
                "content": {"text": text},
                "timestamp": now,
                "metadata": {k: {"stringValue": v} for k, v in md.items()},
            }
            for text, md in items
        ],
    )
    failed = resp.get("failedRecords", [])
    print(f"{namespace}: {len(resp.get('successfulRecords', []))} created, {len(failed)} failed")
    for f in failed:
        print("  ", f.get("errorMessage"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="delete demo records first")
    p.add_argument("--offer-only", action="store_true", help="restore just the Scene 2 offer")
    args = p.parse_args()

    seed = json.loads((ROOT / "data" / "seed.json").read_text())
    cid = seed["customers"][0]["customer_id"]
    mem = AgentCoreMemory()

    ns_facts = mem._ns("custom_facts", cid)
    ns_proc = mem._ns("procedures")
    ns_gloss = mem._ns("glossary")
    if args.reset:
        for ns in (ns_facts, ns_proc, ns_gloss):
            print(ns, "deleted", mem._delete_where(ns, lambda md: True))

    offer = seed["memories"]["offer"]
    mem.remember(cid, offer["label"], offer["text"], kind=offer["kind"])
    if args.offer_only:
        print(f"{ns_facts}: offer restored")
        return
    for f in seed["memories"]["facts"]:
        mem.remember(cid, f["label"], f["text"], kind=f["kind"])
    print(f"{ns_facts}: offer + {len(seed['memories']['facts'])} fact(s) written")

    records(mem, ns_proc, [
        (f"{p['procedure']}: {p['description']}\n{p['content']}", {"procedure": p["procedure"]})
        for p in seed["procedures"]
    ])
    records(mem, ns_gloss, [
        (f"{g['term']}: {g['definition']}", {"term": g["term"], "domain": "cards"}) for g in seed["glossary"]
    ])


if __name__ == "__main__":
    main()
