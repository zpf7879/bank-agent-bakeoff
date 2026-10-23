"""AgentMemory for Side B: Atlas Agent Engine memory.

Compare context() with side_a_agentcore/.../memory_agentcore.py: here ranking,
de-duplication and token budgeting happen in one build_context() call.

Atlas Agent Engine is in public preview. Method names follow the docs at the time
of writing; return shapes are read defensively because they may change.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

from bakeoff.ports import MemoryContext, estimate_tokens

FORMAT_RESERVE = 500  # build_context subtracts this from max_tokens before selecting memories
TOKEN_TTL_SECONDS = 3000  # service-account tokens last one hour; renew early


class HostedMemory:
    """Hosted Memory client authenticated as the bakeoff service account.

    A deployed agent's app.memory runs as whoever invoked it, and a service-account
    caller may not name another user, so per-customer reads through app.memory get 403.
    A service-account token on the hosted client may name any end user as user_id:
    the documented pattern for one backend serving many customers. Side A does the
    same with one IAM role naming each customer as actorId.
    """

    def __init__(self, client_id: str, client_secret: str, project_id: str, base_url: str | None = None):
        self._creds = (client_id, client_secret)
        self._project_id = project_id
        self._base_url = base_url or os.getenv("AE_BASE_URL", "https://agentengine.mongodb.com")
        self._memory: Any = None
        self._minted_at = 0.0

    @classmethod
    def from_env(cls) -> "HostedMemory | None":
        client_id, secret = os.getenv("AE_CLIENT_ID"), os.getenv("AE_CLIENT_SECRET")
        project_id = os.getenv("AE_PROJECT_ID") or os.getenv("PROJECT_ID")  # the platform injects PROJECT_ID
        if not (client_id and secret and project_id):
            return None
        return cls(client_id, secret, project_id)

    def __call__(self) -> Any:
        if self._memory is None or time.time() - self._minted_at > TOKEN_TTL_SECONDS:
            import httpx
            from agent_engine_sdk_memory import Memory

            resp = httpx.post(f"{self._base_url}/api/v1/oauth/token", auth=self._creds,
                              data={"grant_type": "client_credentials"}, timeout=30)
            resp.raise_for_status()
            if self._memory is not None:
                self._memory.close()
            self._memory = Memory(service_account_token=resp.json()["access_token"], project_id=self._project_id)
            self._minted_at = time.time()
        return self._memory


def _emit_memory_event(ctx: MemoryContext) -> None:
    """Stream the memory stats to the caller, like Side A's response fields.

    Agent Engine returns only the agent's text, so this sends a "memory" chunk on
    invokeStream. Best effort: a no-op outside a platform execution.
    """
    try:
        import json

        from agent_engine_runner_shared import emit

        emit("memory", json.dumps({"memory_context_tokens": ctx.token_estimate, "memory_sources": ctx.sources}))
    except Exception:
        pass


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
        counts = {k: int(v) for k, v in (getattr(meta, "memory_counts", None) or {}).items() if v}
        ctx = MemoryContext(
            text=str(text),
            token_estimate=int(tokens) if tokens else estimate_tokens(str(text)),
            sources=counts or {"build_context": 1},
            notes=["ranked, de-duplicated and budgeted by the platform"],
        )
        _emit_memory_event(ctx)
        return ctx

    def remember(self, customer_id: str, label: str, text: str, kind: str = "fact") -> str:
        result = self._get().save_semantic(
            text=text,
            label=label,
            user_id=customer_id,
            metadata={"kind": kind, "customer_id": customer_id},
            upsert=True,  # replaces the memory with the same label
        )
        # A refused write (for example 403) comes back unacknowledged instead of raising.
        # Raise so the tool reports failure and the model doesn't claim it saved.
        if not getattr(result, "acknowledged", result):
            raise RuntimeError(f"memory write not acknowledged for {customer_id}/{label}")
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
