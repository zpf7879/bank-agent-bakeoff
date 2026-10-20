"""Seed Atlas Agent Engine memory for the demo (Side B), through the hosted memory service.

Writes, for customer C-1001:
  - the pre-qualified limit-increase offer (Scene 2), semantic memory
  - a contact preference, semantic memory
and, shared project-wide (visibility "org"):
  - the bank's procedures, procedural memory (Scene 3)
  - the bank's glossary, taxonomic memory (Scene 4)

Usage:
  python side_b_atlas/scripts/seed_memory.py

Run procedures and glossary once: the hosted procedure route is create-only, so a
second run adds duplicates. Semantic memories upsert by label and are safe to re-run.
"""
from __future__ import annotations

import argparse

from _common import hosted_memory, seed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--offer-only", action="store_true", help="restore just the Scene 2 offer (safe to repeat)")
    args = p.parse_args()

    data, mem = seed(), hosted_memory()
    cid = data["customers"][0]["customer_id"]

    offer = data["memories"]["offer"]
    mem.save_semantic(text=offer["text"], label=offer["label"], user_id=cid,
                      metadata={"kind": offer["kind"], "customer_id": cid}, upsert=True)
    if args.offer_only:
        print(f"semantic: offer restored for {cid}")
        mem.close()
        return
    for f in data["memories"]["facts"]:
        mem.save_semantic(text=f["text"], label=f["label"], user_id=cid,
                          metadata={"kind": f["kind"], "customer_id": cid}, upsert=True)
    print(f"semantic: offer + {len(data['memories']['facts'])} fact(s) for {cid}")

    for p in data["procedures"]:
        mem.save_procedure(procedure=p["procedure"], description=p["description"], content=p["content"],
                           tags=p["tags"], visibility="org", user_id=cid)
    print(f"procedural: {len(data['procedures'])} procedure(s), visibility org")

    for g in data["glossary"]:
        mem.save_taxonomic(domain="cards", term=g["term"], definition=g["definition"], visibility="org", user_id=cid)
    print(f"taxonomic: {len(data['glossary'])} term(s) in domain 'cards', visibility org")
    mem.close()


if __name__ == "__main__":
    main()
