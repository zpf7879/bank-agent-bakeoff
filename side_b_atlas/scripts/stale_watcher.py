"""Side B, Scene 2: keep agent memory in step with the account record.

A change stream on harbourline.accounts sees the fraud freeze the moment it is
committed, in the same cluster that holds agent memory. The watcher then
replaces the offer memory (upsert by label) so the agent stops repeating it.

Compare with side_a_agentcore/stale_sync/: aws_lambda extension + Aurora IAM role +
trigger + Lambda + Lambda IAM role, and a fuzzy text match for extracted records.

Usage (run before the freeze, leave it running):
  python side_b_atlas/scripts/stale_watcher.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from _common import bank_db, hosted_memory, seed

OFFER = seed()["memories"]["offer"]
PIPELINE = [
    {"$match": {"operationType": {"$in": ["update", "replace"]}}},
    {"$match": {"$or": [
        {"updateDescription.updatedFields.status": {"$exists": True}},
        {"operationType": "replace"},
    ]}},
]


def withdraw_offer(mem, customer_id: str) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    mem.save_semantic(
        label=OFFER["label"],  # same label, so upsert replaces the old offer
        text=(f"WITHDRAWN on {today}: the earlier credit limit increase offer no longer applies. "
              "The account has a hold. Do not offer or discuss limit increases; a specialist will contact the customer."),
        user_id=customer_id,
        metadata={"kind": "offer", "customer_id": customer_id, "stale": True, "stale_reason": "account hold"},
        upsert=True,
    )


def main() -> None:
    db = bank_db()
    mem = hosted_memory()  # token lasts one hour; restart the watcher for longer sessions
    print(f"Watching {db.name}.accounts for status changes ...")
    with db.accounts.watch(PIPELINE, full_document="updateLookup") as stream:
        for change in stream:
            doc = change.get("fullDocument") or {}
            cid, status = doc.get("customer_id"), doc.get("status")
            if not cid:
                continue
            if status != "active":
                withdraw_offer(mem, cid)
                print(f"{datetime.now():%H:%M:%S} {cid} -> {status}: offer memory withdrawn")
            else:
                print(f"{datetime.now():%H:%M:%S} {cid} -> active: no change")


if __name__ == "__main__":
    main()
