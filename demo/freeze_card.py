"""Scene 2: fraud operations put the card on hold (or release it) in each system of record.

Usage:
  python demo/freeze_card.py --status frozen   # both sides
  python demo/freeze_card.py --status active   # reset after the scene
  python demo/freeze_card.py --status frozen --side a

Side A: UPDATE in Aurora (BANK_PG_DSN). Fires the stale-sync trigger if you installed it.
Side B: update in Atlas (MONGODB_URI). The change stream watcher reacts if it is running.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime

CUSTOMER_ID = "C-1001"


def side_a(status: str) -> None:
    import psycopg

    with psycopg.connect(os.environ["BANK_PG_DSN"]) as conn:
        conn.execute(
            "UPDATE accounts SET status = %s, hold_reason = %s, updated_at = now() WHERE customer_id = %s",
            (status, "fraud review" if status != "active" else None, CUSTOMER_ID),
        )
    print(f"{datetime.now():%H:%M:%S} Side A (Aurora): {CUSTOMER_ID} -> {status}")


def side_b(status: str) -> None:
    from pymongo import MongoClient

    db = MongoClient(os.environ["MONGODB_URI"])[os.getenv("BANK_DB", "harbourline")]
    db.accounts.update_one(
        {"customer_id": CUSTOMER_ID},
        {"$set": {"status": status, "hold_reason": "fraud review" if status != "active" else None}},
    )
    print(f"{datetime.now():%H:%M:%S} Side B (Atlas):  {CUSTOMER_ID} -> {status}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--status", choices=["frozen", "active"], required=True)
    p.add_argument("--side", choices=["a", "b", "both"], default="both")
    args = p.parse_args()
    if args.side in ("a", "both"):
        side_a(args.status)
    if args.side in ("b", "both"):
        side_b(args.status)


if __name__ == "__main__":
    main()
