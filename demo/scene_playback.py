"""Run one bake-off scene's Side B database commands and record each one.

The calls go through the real Atlas bank adapter (`card_agent.bank_atlas`) and
the same filters as `freeze_card.py`, `stale_watcher.py`, and `audit_join.py`.
Memory writes land in `harbourline` as well, which is the optional
`MONGOMEM_DB_NAME=harbourline` layout the Scene 2 `$lookup` depends on.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "side_b_atlas" / "agents" / "card-agent"))

from card_agent.bank_atlas import AtlasBank  # noqa: E402

from local_mongo import LocalDatabase  # noqa: E402
from query_log import QueryLog, monitor_step  # noqa: E402

CUSTOMER_ID = "C-1001"
DEMO_DAY = date(2026, 10, 21)
SEED = json.loads((ROOT / "data" / "seed.json").read_text())

# Identical to side_b_atlas/scripts/stale_watcher.py PIPELINE.
WATCH_PIPELINE = [
    {"$match": {"operationType": {"$in": ["update", "replace"]}}},
    {"$match": {"$or": [
        {"updateDescription.updatedFields.status": {"$exists": True}},
        {"operationType": "replace"},
    ]}},
]

# Same offer test as side_b_atlas/scripts/audit_join.py.
OFFER_RX = re.compile(r"offer|pre-?qualified|limit increase", re.I)

TITLES = {
    "residency": "Where memory lives",
    "stale": "Fraud freeze",
    "procedural": "Fee-waiver procedure",
    "taxonomic": "Bank vocabulary",
    "context": "Context assembly",
}


def audit_pipeline(coll: str = "semantic", user_field: str = "user_id", text_field: str = "text") -> list[dict[str, Any]]:
    """The single-cluster audit from audit_join.py (memory stored in the bank database)."""
    query = {
        text_field: {"$regex": OFFER_RX.pattern, "$options": "i"},
        "metadata.stale": {"$ne": True},
    }
    return [
        {"$match": {"status": {"$ne": "active"}}},
        {"$lookup": {
            "from": coll,
            "localField": "customer_id",
            "foreignField": user_field,
            "pipeline": [{"$match": query}],
            "as": "mem",
        }},
        {"$unwind": "$mem"},
        {"$project": {"_id": 0, "customer_id": 1, "status": 1, "memory": f"$mem.{text_field}"}},
    ]


def _pattern(text: str) -> str:
    return re.escape(text.strip()).replace(r"\ ", "[- ]")


class CollectionMemory:
    """AgentMemory backed by collections in the bank database, so each read and write is a real command."""

    def __init__(self, db: LocalDatabase, offer_label: str):
        self.db = db
        self.offer_label = offer_label

    def context(self, customer_id: str, query: str, session_id: str | None = None) -> dict[str, Any]:
        del query, session_id
        with monitor_step("build_context · semantic memories for this customer", "memory"):
            semantic = self.db.semantic.find({"user_id": customer_id})
        with monitor_step("build_context · episodic memories for this customer", "memory"):
            episodic = self.db.episodic.find({"user_id": customer_id})
        return {"semantic": len(semantic), "episodic": len(episodic)}

    def remember(self, customer_id: str, label: str, text: str, kind: str = "fact") -> str:
        with monitor_step(f"save_semantic · {label}", "memory"):
            self.db.semantic.update_one(
                {"user_id": customer_id, "label": label},
                {"$set": {
                    "text": text,
                    "user_id": customer_id,
                    "label": label,
                    "metadata": {"kind": kind, "customer_id": customer_id},
                }},
                upsert=True,
            )
        return label

    def find_procedure(self, task: str) -> str | None:
        with monitor_step(f"discover_procedures({task!r})", "memory"):
            hits = self.db.procedural.find({
                "visibility": "org",
                "$or": [
                    {"procedure": {"$regex": _pattern(task), "$options": "i"}},
                    {"description": {"$regex": _pattern(task), "$options": "i"}},
                    {"content": {"$regex": _pattern(task), "$options": "i"}},
                ],
            })
        if not hits:
            return None
        name = hits[0]["procedure"]
        with monitor_step(f"get_procedure({name!r}, visibility='org')", "memory"):
            full = self.db.procedural.find_one({"procedure": name, "visibility": "org"})
        if not full:
            return None
        return f"{name}: {full.get('content', '')}"

    def define_term(self, term: str) -> str | None:
        with monitor_step(f"search_taxonomic({term!r}, domain='cards')", "memory"):
            hits = self.db.taxonomic.find({
                "domain": "cards",
                "visibility": "org",
                "term": {"$regex": term.strip(), "$options": "i"},
            })
        if not hits:
            return None
        return str(hits[0].get("definition") or "")

    def withdraw_offer(self, customer_id: str) -> None:
        text = (
            f"WITHDRAWN on {DEMO_DAY.isoformat()}: the earlier credit limit increase offer no longer applies. "
            "The account has a hold. Do not offer or discuss limit increases; a specialist will contact the customer."
        )
        with monitor_step("Watcher: withdraw the offer memory (upsert on the same label)", "memory"):
            self.db.semantic.update_one(
                {"user_id": customer_id, "label": self.offer_label},
                {"$set": {
                    "text": text,
                    "metadata": {
                        "kind": "offer",
                        "customer_id": customer_id,
                        "stale": True,
                        "stale_reason": "account hold",
                    },
                }},
                upsert=True,
            )


def load_bank(db: LocalDatabase) -> None:
    data = SEED
    cid = data["customers"][0]["customer_id"]
    db.drop_all()
    db.seed_docs("customers", data["customers"])
    db.seed_docs("accounts", data["accounts"])
    db.seed_docs("disputes", data["disputes"])
    db.seed_docs("fee_waivers", [])
    offer = data["memories"]["offer"]
    semantic = [{
        "user_id": cid,
        "label": offer["label"],
        "text": offer["text"],
        "metadata": {"kind": offer["kind"], "customer_id": cid},
    }]
    for fact in data["memories"]["facts"]:
        semantic.append({
            "user_id": cid,
            "label": fact["label"],
            "text": fact["text"],
            "metadata": {"kind": fact["kind"], "customer_id": cid},
        })
    db.seed_docs("semantic", semantic)
    db.seed_docs("procedural", [{**proc, "visibility": "org"} for proc in data["procedures"]])
    db.seed_docs("taxonomic", [
        {"domain": "cards", "term": term["term"], "definition": term["definition"], "visibility": "org"}
        for term in data["glossary"]
    ])
    db.seed_docs("episodic", [{
        "user_id": cid,
        "text": "Customer said they are moving to Melbourne for work next month and will keep using the card there.",
        "metadata": {"kind": "episode", "customer_id": cid},
    }])


def play_residency(db: LocalDatabase, bank: AtlasBank, memory: CollectionMemory) -> None:
    del bank
    with monitor_step("Short-term memory: store the customer turn", "memory"):
        db.short_term.insert_one({
            "user_id": CUSTOMER_ID,
            "role": "user",
            "text": "I'm moving to Melbourne for work next month. I'll keep using this card there.",
        })
    memory.remember(
        CUSTOMER_ID,
        "relocation",
        "Customer is relocating to Melbourne for work next month and will keep using this card there.",
        kind="fact",
    )


def play_stale(db: LocalDatabase, bank: AtlasBank, memory: CollectionMemory) -> None:
    del bank
    with monitor_step("System of record: fraud ops freezes the card", "bank"):
        db.accounts.update_one(
            {"customer_id": CUSTOMER_ID},
            {"$set": {"status": "frozen", "hold_reason": "fraud review"}},
        )
    with monitor_step("Change stream: watch accounts for a status change", "stream"):
        db.accounts.watch(WATCH_PIPELINE, full_document="updateLookup")
    with monitor_step("Audit: frozen customers whose memory still holds an offer", "audit"):
        db.accounts.aggregate(audit_pipeline())
    memory.withdraw_offer(CUSTOMER_ID)
    with monitor_step("Audit again, after the watcher withdraws the offer", "audit"):
        db.accounts.aggregate(audit_pipeline())
    memory.context(CUSTOMER_ID, "credit limit increase")


def play_procedural(db: LocalDatabase, bank: AtlasBank, memory: CollectionMemory) -> None:
    """Same order as check_fee_waiver_eligibility and apply_fee_waiver in shared/bakeoff/tools.py."""
    del db
    memory.find_procedure("late fee waiver")
    with monitor_step("Tool check_fee_waiver_eligibility", "bank"):
        bank.get_customer(CUSTOMER_ID)
        bank.get_account(CUSTOMER_ID)
        bank.last_fee_waiver(CUSTOMER_ID)
    with monitor_step("Tool apply_fee_waiver", "bank"):
        account = bank.get_account(CUSTOMER_ID) or {}
        amount = float(account.get("late_fee_sgd", 0) or 0)
        bank.record_fee_waiver(CUSTOMER_ID, amount, "LFW-01")


def play_taxonomic(db: LocalDatabase, bank: AtlasBank, memory: CollectionMemory) -> None:
    del db
    with monitor_step("Tool get_dispute_status", "bank"):
        bank.get_open_dispute(CUSTOMER_ID)
    memory.define_term("provisional credit")


def play_context(db: LocalDatabase, bank: AtlasBank, memory: CollectionMemory) -> None:
    del db, bank
    memory.context(
        CUSTOMER_ID,
        "Remind me what we discussed about my Melbourne move. Anything I still need to do?",
    )


PLAYERS = {
    "residency": play_residency,
    "stale": play_stale,
    "procedural": play_procedural,
    "taxonomic": play_taxonomic,
    "context": play_context,
}


def play_scene(scene_id: str, log: QueryLog | None = None) -> dict[str, Any]:
    player = PLAYERS[scene_id]
    log = log or QueryLog()
    log.clear()
    log.scene = scene_id
    log.title = TITLES[scene_id]
    db = LocalDatabase(log)
    load_bank(db)
    memory = CollectionMemory(db, SEED["memories"]["offer"]["label"])
    bank = AtlasBank(database=db, today=lambda: DEMO_DAY)
    print(f"\nScene · {TITLES[scene_id]}")
    player(db, bank, memory)
    return log.snapshot()
