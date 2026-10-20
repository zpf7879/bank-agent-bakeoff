"""Side B, Scenes 1 and 2: query agent memory next to the bank's own data.

  --inspect   list the memory database's collections and the fields of one sample
              document (embeddings hidden). Run this once after the first deploy:
              Atlas Agent Engine is in preview and its memory schema is not documented.
  (default)   audit: every customer on hold whose agent memory still mentions an offer.

The memory database defaults to mdb_memory_<project-id>. If you set MONGOMEM_DB_NAME
to the bank database (harbourline), the audit runs as a single $lookup. Otherwise it
runs as two queries over one connection to the same cluster.

Usage:
  python side_b_atlas/scripts/audit_join.py --inspect
  python side_b_atlas/scripts/audit_join.py [--memory-coll NAME] [--user-field NAME] [--text-field NAME]
"""
from __future__ import annotations

import argparse
import os
import re

from pymongo import MongoClient

BANK_DB = os.getenv("BANK_DB", "harbourline")
OFFER_RX = re.compile(r"offer|pre-?qualified|limit increase", re.I)


def memory_db_name(client: MongoClient) -> str:
    if os.getenv("MONGOMEM_DB_NAME"):
        return os.environ["MONGOMEM_DB_NAME"]
    names = [n for n in client.list_database_names() if n.startswith("mdb_memory")]
    if not names:
        raise SystemExit("No mdb_memory_* database found. Set MONGOMEM_DB_NAME.")
    return names[0]


def short(value, depth: int = 0):
    if isinstance(value, list) and value and isinstance(value[0], float):
        return f"<vector[{len(value)}]>"
    if isinstance(value, dict) and depth < 2:
        return {k: short(v, depth + 1) for k, v in value.items()}
    if isinstance(value, str) and len(value) > 80:
        return value[:77] + "..."
    return value


def inspect(client: MongoClient, mem_db: str) -> None:
    db = client[mem_db]
    print(f"Cluster: {client.address}\nMemory database: {mem_db}  |  Bank database: {BANK_DB}\n")
    for name in sorted(db.list_collection_names()):
        print(f"- {name}: {db[name].estimated_document_count()} docs")
        sample = db[name].find_one()
        if sample:
            print("   ", short(sample))


def audit(client: MongoClient, mem_db: str, coll: str, user_field: str, text_field: str) -> None:
    bank, mem = client[BANK_DB], client[mem_db][coll]
    query = {text_field: {"$regex": OFFER_RX.pattern, "$options": "i"},
             "metadata.stale": {"$ne": True}}

    if mem_db == BANK_DB:
        rows = list(bank.accounts.aggregate([
            {"$match": {"status": {"$ne": "active"}}},
            {"$lookup": {"from": coll, "localField": "customer_id", "foreignField": user_field,
                         "pipeline": [{"$match": query}], "as": "mem"}},
            {"$unwind": "$mem"},
            {"$project": {"_id": 0, "customer_id": 1, "status": 1, "memory": f"$mem.{text_field}"}},
        ]))
        how = "one $lookup"
    else:
        held = {a["customer_id"]: a["status"] for a in bank.accounts.find({"status": {"$ne": "active"}})}
        rows = [{"customer_id": m[user_field], "status": held[m[user_field]], "memory": m.get(text_field)}
                for m in mem.find({**query, user_field: {"$in": list(held)}})]
        how = "two queries, one cluster"

    print(f"Customers on hold whose agent memory still holds an offer ({how}): {len(rows)}")
    for r in rows:
        print(f"  {r['customer_id']} [{r['status']}]  {str(r['memory'])[:100]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--memory-coll", default=os.getenv("MEMORY_SEMANTIC_COLL", "semantic"))
    p.add_argument("--user-field", default=os.getenv("MEMORY_USER_FIELD", "user_id"))
    p.add_argument("--text-field", default=os.getenv("MEMORY_TEXT_FIELD", "text"))
    args = p.parse_args()

    client = MongoClient(os.environ["MONGODB_URI"], appname="bakeoff-audit")
    mem_db = memory_db_name(client)
    if args.inspect:
        inspect(client, mem_db)
    else:
        audit(client, mem_db, args.memory_coll, args.user_field, args.text_field)


if __name__ == "__main__":
    main()
