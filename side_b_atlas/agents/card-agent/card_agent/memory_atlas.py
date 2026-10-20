"""AgentMemory for Side B: Atlas Agent Engine memory.

Compare context() with side_a_agentcore/.../memory_agentcore.py: here ranking,
de-duplication and token budgeting happen in one build_context() call.

Atlas Agent Engine is in public preview. Method names follow the docs at the time
of writing; return shapes are read defensively because they may change.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from bakeoff.ports import MemoryContext, estimate_tokens

FORMAT_RESERVE = 500  # build_context subtracts this from max_tokens before selecting memories


def _first_attr(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and obj.get(name):
            return obj[name]
        value = getattr(obj, name, None)
        if value:
            return value
    return None


class AtlasMemory:
    def __init__(self, get_memory: Callable[[], Any], max_context_tokens: int | None = None):
        # get_memory is lazy (lambda: app.memory) because app.memory is bound per request.
        self._get = get_memory
        self.max_context_tokens = max_context_tokens or int(os.getenv("MAX_CONTEXT_TOKENS", "1500"))

    def context(self, customer_id: str, query: str, session_id: str | None = None) -> MemoryContext:
        res = self._get().build_context(
            query=query or "customer",
            user_id=customer_id,
            enabled_sources={"semantic", "episodic"},
            max_tokens=self.max_context_tokens + FORMAT_RESERVE,  # same memory budget as Side A
        )
        text = res if isinstance(res, str) else (_first_attr(res, "formatted_context") or "")
        meta = None if isinstance(res, str) else getattr(res, "metadata", None)
        tokens = getattr(meta, "token_count", None) if meta is not None else None
        return MemoryContext(
            text=str(text),
            token_estimate=int(tokens) if tokens else estimate_tokens(str(text)),
            sources={"build_context": 1},
            notes=["ranked, de-duplicated and budgeted by the platform"],
        )

    def remember(self, customer_id: str, label: str, text: str, kind: str = "fact") -> str:
        result = self._get().save_semantic(
            text=text,
            label=label,
            user_id=customer_id,
            metadata={"kind": kind, "customer_id": customer_id},
            upsert=True,  # replaces the memory with the same label
        )
        return str(_first_attr(result, "id", "memory_id") or "saved")

    def find_procedure(self, task: str) -> str | None:
        mem = self._get()
        hits = mem.discover_procedures(task, visibility="org", top_k=1)
        if not hits:
            return None
        hit = hits[0]
        name = _first_attr(hit, "procedure", "procedure_name", "name")
        full = mem.get_procedure(name, visibility="org") if name else None
        content = _first_attr(full, "content") or _first_attr(hit, "content", "description")
        return f"{name}: {content}" if name else str(content)

    def define_term(self, term: str) -> str | None:
        hits = self._get().search_taxonomic(term, domain="cards", visibility="org", top_k=1)
        if not hits:
            return None
        hit = hits[0]
        return str(_first_attr(hit, "content", "text", "definition") or hit)
