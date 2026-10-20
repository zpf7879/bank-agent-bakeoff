"""BankData for Side B: collections in the same Atlas cluster that stores agent memory."""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from pymongo import MongoClient


class AtlasBank:
    def __init__(self, uri: str | None = None, db_name: str | None = None):
        self._uri = uri or os.environ["MONGODB_URI"]  # injected by Atlas Agent Engine
        self._db_name = db_name or os.getenv("BANK_DB", "harbourline")
        self._client: MongoClient | None = None

    @property
    def db(self):
        if self._client is None:
            self._client = MongoClient(self._uri, appname="harbourline-card-agent")
        return self._client[self._db_name]

    def get_account(self, customer_id: str) -> dict[str, Any] | None:
        return self.db.accounts.find_one({"customer_id": customer_id}, {"_id": 0})

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return self.db.customers.find_one({"customer_id": customer_id}, {"_id": 0})

    def last_fee_waiver(self, customer_id: str) -> dict[str, Any] | None:
        return self.db.fee_waivers.find_one({"customer_id": customer_id}, {"_id": 0}, sort=[("waived_on", -1)])

    def record_fee_waiver(self, customer_id: str, amount_sgd: float, reason_code: str) -> dict[str, Any]:
        doc = {
            "customer_id": customer_id,
            "amount_sgd": amount_sgd,
            "reason_code": reason_code,
            "waived_on": date.today().isoformat(),
        }
        self.db.fee_waivers.insert_one(dict(doc))
        self.db.accounts.update_one({"customer_id": customer_id}, {"$set": {"late_fee_sgd": 0}})
        return {"waived": True, **doc}

    def request_limit_increase(self, customer_id: str, new_limit_sgd: int) -> dict[str, Any]:
        acct = self.get_account(customer_id)
        if not acct:
            return {"accepted": False, "reason": "account not found"}
        if acct.get("status") != "active":
            return {"accepted": False, "reason": "blocked: refer to specialist"}
        self.db.limit_requests.insert_one(
            {"customer_id": customer_id, "requested_limit_sgd": new_limit_sgd, "status": "submitted"}
        )
        return {"accepted": True, "requested_limit_sgd": new_limit_sgd, "status": "submitted"}

    def get_open_dispute(self, customer_id: str) -> dict[str, Any] | None:
        return self.db.disputes.find_one(
            {"customer_id": customer_id, "status": {"$ne": "closed"}}, {"_id": 0}, sort=[("opened", -1)]
        )
