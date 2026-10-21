"""Scene 1: show where customer data and agent memory live on each side.

Side A: the account row is in Aurora; the memory is in AgentCore Memory, reachable
        only through its API. Two systems, two sets of controls.
Side B: the account document and the memory documents come back over ONE connection
        to ONE cluster.

Usage:
  python demo/where_memory_lives.py [--side a|b|both]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "shared"), str(ROOT / "side_a_agentcore" / "app" / "card_agent")]
CUSTOMER_ID = "C-1001"


def show(title: str, obj) -> None:
    print(f"  {title}:")
    text = json.dumps(obj, default=str, indent=2)
    print("\n".join("    " + ln for ln in text.splitlines()[:25]))


def side_a() -> None:
    import boto3
    from psycopg.rows import dict_row

    from bank_aurora import connect
    from memory_agentcore import AgentCoreMemory

    print("\n=== Side A · AgentCore ===")
    with connect(row_factory=dict_row) as conn:
        row = conn.execute("SELECT account_id, status, credit_limit_sgd FROM accounts WHERE customer_id = %s",
                           (CUSTOMER_ID,)).fetchone()
    show("System 1 · Aurora PostgreSQL · accounts row", row)

    mem = AgentCoreMemory()
    records = []
    for key in ("custom_facts", "facts", "preferences"):
        for rec in mem._list(mem._ns(key, CUSTOMER_ID)):
            records.append({"namespace": key, "text": (rec.get("content") or {}).get("text", "")[:90]})
    show("System 2 · AgentCore Memory · records (via API only)", records)

    ctl = boto3.client("bedrock-agentcore-control", region_name=(os.getenv("AWS_REGION") or "ap-southeast-1"))
    m = ctl.get_memory(memoryId=mem.memory_id)["memory"]
    show("AgentCore Memory settings", {
        "customer_managed_key": m.get("encryptionKeyArn") or "none (service-managed key)",
        "event_expiry_days": m.get("eventExpiryDuration"),
    })
    print("  -> Two systems: encryption, backup, access control and audit are configured and evidenced twice.")


def side_b() -> None:
    from pymongo import MongoClient

    print("\n=== Side B · Atlas Agent Engine ===")
    client = MongoClient(os.environ["MONGODB_URI"])
    bank = client[os.getenv("BANK_DB", "harbourline")]
    mem_db_name = os.getenv("MONGOMEM_DB_NAME") or next(
        (n for n in client.list_database_names() if n.startswith("mdb_memory")), None)
    print(f"  One cluster: {client.address}")
    show(f"{bank.name}.accounts", bank.accounts.find_one({"customer_id": CUSTOMER_ID},
                                                        {"_id": 0, "account_id": 1, "status": 1, "credit_limit_sgd": 1}))
    if not mem_db_name:
        print("  No mdb_memory_* database yet. Seed memory first.")
        return
    user_field = os.getenv("MEMORY_USER_FIELD", "user_id")
    found = []
    for coll in client[mem_db_name].list_collection_names():
        for doc in client[mem_db_name][coll].find({user_field: CUSTOMER_ID}).limit(3):
            text = doc.get("text") or doc.get("content") or ""
            found.append({"collection": f"{mem_db_name}.{coll}", "text": str(text)[:90]})
    show("Agent memory documents for the same customer, same cluster", found)
    print("  -> One system: the cluster's encryption, backup, access control and audit log already cover memory.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--side", choices=["a", "b", "both"], default="both")
    args = p.parse_args()
    if args.side in ("a", "both"):
        side_a()
    if args.side in ("b", "both"):
        side_b()


if __name__ == "__main__":
    main()
