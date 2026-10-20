"""BankData for Side A: Aurora PostgreSQL (the bank's system of record)."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _dsn() -> str:
    dsn = os.getenv("BANK_PG_DSN")
    if dsn:
        return dsn
    secret_arn = os.getenv("BANK_PG_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("Set BANK_PG_DSN or BANK_PG_SECRET_ARN")
    import boto3

    secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"])
    return (
        f"host={secret['host']} port={secret.get('port', 5432)} dbname={secret.get('dbname', 'harbourline')} "
        f"user={secret['username']} password={secret['password']} sslmode=require"
    )


class AuroraBank:
    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _dsn()

    def _one(self, sql: str, *params: Any) -> dict[str, Any] | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            return conn.execute(sql, params).fetchone()

    def get_account(self, customer_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM accounts WHERE customer_id = %s", customer_id)

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM customers WHERE customer_id = %s", customer_id)

    def last_fee_waiver(self, customer_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM fee_waivers WHERE customer_id = %s ORDER BY waived_on DESC LIMIT 1", customer_id
        )

    def record_fee_waiver(self, customer_id: str, amount_sgd: float, reason_code: str) -> dict[str, Any]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            row = conn.execute(
                "INSERT INTO fee_waivers (customer_id, amount_sgd, reason_code, waived_on) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (customer_id, amount_sgd, reason_code, date.today()),
            ).fetchone()
            conn.execute("UPDATE accounts SET late_fee_sgd = 0 WHERE customer_id = %s", (customer_id,))
        return {"waived": True, **row}

    def request_limit_increase(self, customer_id: str, new_limit_sgd: int) -> dict[str, Any]:
        acct = self.get_account(customer_id)
        if not acct:
            return {"accepted": False, "reason": "account not found"}
        if acct["status"] != "active":
            # The system of record blocks it. The agent's risk is what it SAID before this call.
            return {"accepted": False, "reason": "blocked: refer to specialist"}
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO limit_requests (customer_id, requested_limit_sgd, status) VALUES (%s, %s, 'submitted')",
                (customer_id, new_limit_sgd),
            )
        return {"accepted": True, "requested_limit_sgd": new_limit_sgd, "status": "submitted"}

    def get_open_dispute(self, customer_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM disputes WHERE customer_id = %s AND status <> 'closed' ORDER BY opened DESC LIMIT 1",
            customer_id,
        )
