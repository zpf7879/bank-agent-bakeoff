"""Create tables and load data/seed.json into Aurora PostgreSQL (Side A).

Usage:
  export BANK_PG_DSN="host=... port=5432 dbname=harbourline user=... password=... sslmode=require"
  python side_a_agentcore/scripts/seed_aurora.py [--reset]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="truncate tables first")
    args = parser.parse_args()

    seed = json.loads((ROOT / "data" / "seed.json").read_text())
    schema = (Path(__file__).with_name("schema.sql")).read_text()

    with psycopg.connect(os.environ["BANK_PG_DSN"]) as conn:
        conn.execute(schema)
        if args.reset:
            conn.execute("TRUNCATE limit_requests, fee_waivers, disputes, accounts, customers CASCADE")
        for c in seed["customers"]:
            conn.execute(
                "INSERT INTO customers VALUES (%(customer_id)s, %(name)s, %(customer_since)s, %(segment)s, "
                "%(email)s, %(mailing_address)s) ON CONFLICT (customer_id) DO NOTHING",
                c,
            )
        for a in seed["accounts"]:
            conn.execute(
                "INSERT INTO accounts (account_id, customer_id, product, card_last4, status, hold_reason, "
                "credit_limit_sgd, balance_sgd, overdue_sgd, late_fee_sgd, late_fee_date, last_payment_date) "
                "VALUES (%(account_id)s, %(customer_id)s, %(product)s, %(card_last4)s, %(status)s, %(hold_reason)s, "
                "%(credit_limit_sgd)s, %(balance_sgd)s, %(overdue_sgd)s, %(late_fee_sgd)s, %(late_fee_date)s, "
                "%(last_payment_date)s) ON CONFLICT (account_id) DO NOTHING",
                a,
            )
        for d in seed["disputes"]:
            conn.execute(
                "INSERT INTO disputes VALUES (%(dispute_id)s, %(customer_id)s, %(merchant)s, %(amount_sgd)s, "
                "%(opened)s, %(status)s, %(provisional_credit_sgd)s) ON CONFLICT (dispute_id) DO NOTHING",
                d,
            )
    print("Aurora seeded:", len(seed["customers"]), "customer(s)")


if __name__ == "__main__":
    main()
