"""BankData for Side A: Aurora PostgreSQL (the bank's system of record)."""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row


def _iam_auth() -> bool:
    return os.getenv("BANK_PG_IAM_AUTH", "false").lower() == "true"


def _iam_dsn() -> str:
    """IAM database auth: a fresh token per connection, since each token expires after 15 minutes.

    Needs rds-db:connect on the database user for whoever runs this (you, or the runtime role).
    """
    import boto3

    host = os.environ["BANK_PG_HOST"]
    port = int(os.getenv("BANK_PG_PORT", "5432"))
    user = os.getenv("BANK_PG_USER", "postgres")
    region = (os.getenv("AWS_REGION") or "ap-southeast-1")
    token = boto3.client("rds", region_name=region).generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user, Region=region
    )
    return make_conninfo(
        host=host, port=port, dbname=os.getenv("BANK_PG_DBNAME", "harbourline"), user=user,
        password=token, sslmode="require",
    )


def _dsn() -> str:
    if _iam_auth():
        return _iam_dsn()
    dsn = os.getenv("BANK_PG_DSN")
    if dsn:
        return dsn
    secret_arn = os.getenv("BANK_PG_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("Set BANK_PG_IAM_AUTH=true (with BANK_PG_HOST), BANK_PG_DSN or BANK_PG_SECRET_ARN")
    import boto3

    secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"])
    return make_conninfo(
        host=secret["host"], port=secret.get("port", 5432), dbname=secret.get("dbname", "harbourline"),
        user=secret["username"], password=secret["password"], sslmode="require",
    )


def connect(**kwargs: Any) -> psycopg.Connection:
    """Open a connection using whichever BANK_PG_* settings are present. Used by the scripts too."""
    return psycopg.connect(_dsn(), **kwargs)


class AuroraBank:
    def __init__(self, dsn: str | None = None):
        # IAM tokens expire, so they are resolved per connection; anything else is resolved once.
        self._dsn = dsn or (None if _iam_auth() else _dsn())

    def _connect(self, **kwargs: Any) -> psycopg.Connection:
        return psycopg.connect(self._dsn or _dsn(), **kwargs)

    def _one(self, sql: str, *params: Any) -> dict[str, Any] | None:
        with self._connect(row_factory=dict_row) as conn:
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
        with self._connect(row_factory=dict_row) as conn:
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
        with self._connect() as conn:
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
