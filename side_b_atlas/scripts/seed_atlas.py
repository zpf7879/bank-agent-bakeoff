"""Load data/seed.json into the bank database on the Atlas cluster (Side B).

Usage:
  export MONGODB_URI=...    # the cluster linked to Atlas Agent Engine
  python side_b_atlas/scripts/seed_atlas.py [--reset]
"""
from __future__ import annotations

import argparse

from _common import bank_db, seed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()

    data, db = seed(), bank_db()
    if args.reset:
        for name in ("customers", "accounts", "fee_waivers", "limit_requests", "disputes"):
            db[name].drop()

    for c in data["customers"]:
        db.customers.replace_one({"customer_id": c["customer_id"]}, c, upsert=True)
    for a in data["accounts"]:
        db.accounts.replace_one({"account_id": a["account_id"]}, a, upsert=True)
    for d in data["disputes"]:
        db.disputes.replace_one({"dispute_id": d["dispute_id"]}, d, upsert=True)

    db.accounts.create_index("customer_id", unique=True)
    db.fee_waivers.create_index([("customer_id", 1), ("waived_on", -1)])
    db.disputes.create_index([("customer_id", 1), ("opened", -1)])
    print(f"Seeded {db.name}: {db.accounts.count_documents({})} account(s)")


if __name__ == "__main__":
    main()
