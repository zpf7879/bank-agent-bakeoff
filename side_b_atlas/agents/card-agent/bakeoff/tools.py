"""Tool functions shared by both sides.

make_tool_functions() returns plain Python functions with type hints and docstrings.
Each platform registers them its own way:
  Side A: langchain_core.tools.tool(fn)
  Side B: app.tool()(fn)   # Atlas Agent Engine wrapper for audit and policy
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from .ports import AgentMemory, BankData


def _json(obj: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)

    return json.dumps(obj, default=default)


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def make_tool_functions(bank: BankData, memory: AgentMemory, today: Callable[[], date] = date.today) -> list[Callable[..., str]]:
    def get_account_status(customer_id: str) -> str:
        """Get the live status of the customer's card account from the system of record: status, credit limit, balance and overdue amount."""
        acct = bank.get_account(customer_id)
        if not acct:
            return _json({"error": "account not found"})
        # hold_reason is internal; the agent only learns that a hold exists.
        public = {k: v for k, v in acct.items() if k not in ("hold_reason", "_id")}
        public["has_hold"] = acct.get("status") != "active"
        return _json(public)

    def submit_limit_increase(customer_id: str, new_limit_sgd: int) -> str:
        """Submit a credit limit increase request for the customer's card. The core banking system may reject it."""
        return _json(bank.request_limit_increase(customer_id, int(new_limit_sgd)))

    def check_fee_waiver_eligibility(customer_id: str) -> str:
        """Return the facts needed to decide a late-fee waiver: tenure in months, last waiver date, late fee amount and whether the overdue balance is paid."""
        cust = bank.get_customer(customer_id) or {}
        acct = bank.get_account(customer_id) or {}
        last = bank.last_fee_waiver(customer_id)
        since = _to_date(cust.get("customer_since"))
        return _json(
            {
                "tenure_months": _months_between(since, today()) if since else None,
                "last_waiver_date": (last or {}).get("waived_on"),
                "late_fee_sgd": acct.get("late_fee_sgd", 0),
                "overdue_paid": float(acct.get("overdue_sgd", 0) or 0) == 0.0,
            }
        )

    def apply_fee_waiver(customer_id: str, reason_code: str) -> str:
        """Waive the customer's current late fee and log the reason code. Only call after the waiver procedure says the customer is eligible."""
        acct = bank.get_account(customer_id) or {}
        amount = float(acct.get("late_fee_sgd", 0) or 0)
        return _json(bank.record_fee_waiver(customer_id, amount, reason_code))

    def get_dispute_status(customer_id: str) -> str:
        """Get the customer's open card dispute, including any provisional credit."""
        return _json(bank.get_open_dispute(customer_id) or {"open_dispute": None})

    def remember_customer_fact(customer_id: str, label: str, fact: str) -> str:
        """Save a durable fact the customer shared (for example a relocation or a contact preference). Use a short kebab-case label."""
        ref = memory.remember(customer_id, label, fact, kind="fact")
        return _json({"saved": True, "label": label, "ref": ref})

    def find_procedure(task: str) -> str:
        """Look up the bank's step-by-step procedure for a task, such as 'late fee waiver' or 'credit limit increase'."""
        proc = memory.find_procedure(task)
        return proc or "No procedure found. Do not take the action; offer to have a specialist follow up."

    def define_bank_term(term: str) -> str:
        """Look up the bank's approved definition of a banking term, such as 'provisional credit'."""
        definition = memory.define_term(term)
        return definition or "No approved definition found."

    return [
        get_account_status,
        submit_limit_increase,
        check_fee_waiver_eligibility,
        apply_fee_waiver,
        get_dispute_status,
        remember_customer_fact,
        find_procedure,
        define_bank_term,
    ]
