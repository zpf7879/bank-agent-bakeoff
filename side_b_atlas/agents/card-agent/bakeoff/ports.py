"""Interfaces the shared agent depends on.

Each platform supplies its own implementation:
  Side A (AgentCore): Aurora PostgreSQL for BankData, AgentCore Memory for AgentMemory
  Side B (Atlas):     Atlas collections for BankData, Atlas Agent Engine memory for AgentMemory

The agent graph, prompt and tools only see these interfaces, which is what
keeps the comparison apples to apples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class MemoryContext:
    """Prompt-ready memory plus numbers the demo prints."""

    text: str
    token_estimate: int
    sources: dict[str, int] = field(default_factory=dict)  # records used per source
    notes: list[str] = field(default_factory=list)


class BankData(Protocol):
    def get_account(self, customer_id: str) -> dict[str, Any] | None: ...
    def get_customer(self, customer_id: str) -> dict[str, Any] | None: ...
    def last_fee_waiver(self, customer_id: str) -> dict[str, Any] | None: ...
    def record_fee_waiver(self, customer_id: str, amount_sgd: float, reason_code: str) -> dict[str, Any]: ...
    def request_limit_increase(self, customer_id: str, new_limit_sgd: int) -> dict[str, Any]: ...
    def get_open_dispute(self, customer_id: str) -> dict[str, Any] | None: ...


class AgentMemory(Protocol):
    def context(self, customer_id: str, query: str, session_id: str | None = None) -> MemoryContext: ...
    def remember(self, customer_id: str, label: str, text: str, kind: str = "fact") -> str: ...
    def find_procedure(self, task: str) -> str | None: ...
    def define_term(self, term: str) -> str | None: ...


def estimate_tokens(text: str) -> int:
    """Rough estimate (about 4 characters per token). Good enough for side-by-side comparison."""
    return max(0, len(text) // 4)
