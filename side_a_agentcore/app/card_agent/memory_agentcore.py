"""AgentMemory for Side A: Amazon Bedrock AgentCore Memory.

Everything in context() below is glue code the team owns on Side A:
query several namespaces, merge, de-duplicate, rank and trim to a token budget.
Side B gets the same result from one build_context() call. Keep this file honest:
it is the "build-it-yourself" half of Scene 5.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

from bakeoff.ports import MemoryContext, estimate_tokens

HERE = Path(__file__).resolve().parent

# Namespace templates. Strategy namespaces come from the memory resource
# (scripts/describe_memory.py writes them to memory_config.json).
# The bakeoff/* namespaces hold records this demo writes directly.
DEFAULT_NAMESPACES = {
    "facts": "/facts/{actorId}/",
    "preferences": "/preferences/{actorId}/",
    "episodes": "/episodes/{actorId}/",
    "custom_facts": "/bakeoff/facts/{actorId}/",
    "glossary": "/bakeoff/glossary/cards/",
    "procedures": "/bakeoff/procedures/",
}


def _load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {"namespaces": dict(DEFAULT_NAMESPACES)}
    path = HERE / "memory_config.json"
    if path.exists():
        file_cfg = json.loads(path.read_text())
        cfg["memory_id"] = file_cfg.get("memory_id")
        cfg["namespaces"].update(file_cfg.get("namespaces", {}))
    # Environment wins. The AgentCore CLI injects the memory ID as an environment
    # variable when memory is declared in agentcore.json; the exact name varies, so match loosely.
    env_id = os.getenv("AGENTCORE_MEMORY_ID") or os.getenv("MEMORY_ID")
    if not env_id:
        for key, value in os.environ.items():
            if key.startswith("MEMORY_") and key.endswith("_ID") and value:
                env_id = value
                break
    if env_id:
        cfg["memory_id"] = env_id
    if not cfg.get("memory_id"):
        raise RuntimeError("No AgentCore memory ID. Set AGENTCORE_MEMORY_ID or run scripts/describe_memory.py.")
    return cfg


class AgentCoreMemory:
    def __init__(self, region: str | None = None, max_context_tokens: int | None = None):
        cfg = _load_config()
        self.memory_id: str = cfg["memory_id"]
        self.ns: dict[str, str] = cfg["namespaces"]
        self.client = boto3.client("bedrock-agentcore", region_name=region or (os.getenv("AWS_REGION") or "ap-southeast-1"))
        self.max_context_tokens = max_context_tokens or int(os.getenv("MAX_CONTEXT_TOKENS", "1500"))

    # ---------- helpers ----------
    def _ns(self, key: str, actor_id: str = "") -> str:
        return self.ns[key].replace("{actorId}", actor_id).replace("{sessionId}", "")

    def _retrieve(self, namespace: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        try:
            resp = self.client.retrieve_memory_records(
                memoryId=self.memory_id,
                namespace=namespace,
                searchCriteria={"searchQuery": query or "customer", "topK": top_k},
                maxResults=top_k,
            )
        except self.client.exceptions.ResourceNotFoundException:
            return []
        return resp.get("memoryRecordSummaries", [])

    @staticmethod
    def _text(record: dict[str, Any]) -> str:
        return (record.get("content") or {}).get("text", "").strip()

    # ---------- AgentMemory ----------
    def context(self, customer_id: str, query: str, session_id: str | None = None) -> MemoryContext:
        # 1. Query every namespace that may hold something about this customer.
        candidates: list[tuple[str, float, str]] = []
        sources: dict[str, int] = {}
        for key in ("custom_facts", "facts", "preferences", "episodes"):
            for rec in self._retrieve(self._ns(key, customer_id), query, top_k=5):
                text = self._text(rec)
                if text:
                    candidates.append((key, float(rec.get("score") or 0.0), text))

        # 2. De-duplicate (same fact can be written directly and extracted by a strategy).
        seen: set[str] = set()
        unique = []
        for key, score, text in sorted(candidates, key=lambda c: c[1], reverse=True):
            norm = " ".join(text.lower().split())
            if norm in seen:
                continue
            seen.add(norm)
            unique.append((key, score, text))

        # 3. Trim to the token budget, highest score first.
        lines: list[str] = []
        used = 0
        for key, _score, text in unique:
            line = f"- ({key}) {text}"
            cost = estimate_tokens(line)
            if used + cost > self.max_context_tokens:
                break
            lines.append(line)
            used += cost
            sources[key] = sources.get(key, 0) + 1

        text = "\n".join(lines)
        return MemoryContext(text=text, token_estimate=estimate_tokens(text), sources=sources,
                             notes=[f"{len(candidates)} candidates from 4 namespaces, {len(lines)} kept"])

    def remember(self, customer_id: str, label: str, text: str, kind: str = "fact") -> str:
        namespace = self._ns("custom_facts", customer_id)
        # AgentCore has no upsert-by-label, so delete any record with the same label first.
        self._delete_where(namespace, lambda md: md.get("label") == label)
        resp = self.client.batch_create_memory_records(
            memoryId=self.memory_id,
            records=[
                {
                    "requestIdentifier": uuid.uuid4().hex[:16],
                    "namespaces": [namespace],
                    "content": {"text": text},
                    "timestamp": datetime.now(timezone.utc),
                    "metadata": {
                        "label": {"stringValue": label},
                        "kind": {"stringValue": kind},
                        "customer_id": {"stringValue": customer_id},
                    },
                }
            ],
        )
        ok = resp.get("successfulRecords", [])
        return ok[0]["memoryRecordId"] if ok else "failed"

    def find_procedure(self, task: str) -> str | None:
        hits = self._retrieve(self._ns("procedures"), task, top_k=1)
        return self._text(hits[0]) if hits else None

    def define_term(self, term: str) -> str | None:
        hits = self._retrieve(self._ns("glossary"), term, top_k=1)
        return self._text(hits[0]) if hits else None

    # ---------- extras used by main.py and scripts ----------
    def record_turn(self, customer_id: str, session_id: str, role: str, text: str) -> None:
        """Short-term event; built-in strategies extract long-term memory from these asynchronously."""
        self.client.create_event(
            memoryId=self.memory_id,
            actorId=customer_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"conversational": {"content": {"text": text[:9000]}, "role": role}}],
        )

    def _list(self, namespace: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        token = None
        while True:
            kwargs = {"memoryId": self.memory_id, "namespace": namespace, "maxResults": 100}
            if token:
                kwargs["nextToken"] = token
            resp = self.client.list_memory_records(**kwargs)
            out.extend(resp.get("memoryRecordSummaries", []))
            token = resp.get("nextToken")
            if not token:
                return out

    def _delete_where(self, namespace: str, match) -> int:
        doomed = []
        for rec in self._list(namespace):
            md = {k: (v or {}).get("stringValue") for k, v in (rec.get("metadata") or {}).items()}
            if match(md):
                doomed.append({"memoryRecordId": rec["memoryRecordId"], "namespace": namespace})
        if doomed:
            self.client.batch_delete_memory_records(memoryId=self.memory_id, records=doomed)
        return len(doomed)
