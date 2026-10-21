"""In-memory log of the MongoDB commands the bake-off monitor just ran.

Same idea as the GraphRAG workshop inspector: each entry is the real call,
plus mongosh you can paste, plus how long it took and how many docs came back.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any, Iterator

# Set by the scene player so every command inside a tool call shares a label.
_step: ContextVar[dict[str, str]] = ContextVar("monitor_step", default={"label": "", "source": "bank"})


@contextmanager
def monitor_step(label: str, source: str = "bank") -> Iterator[None]:
    token = _step.set({"label": label, "source": source})
    try:
        yield
    finally:
        _step.reset(token)


def current_step() -> dict[str, str]:
    return _step.get()


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


class QueryLog:
    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = Lock()
        self.scene: str | None = None
        self.title: str | None = None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.scene = None
            self.title = None

    def add(
        self,
        *,
        collection: str,
        operation: str,
        mongosh: str,
        result_count: int | None,
        started: float,
        note: str | None = None,
        db: str = "harbourline",
    ) -> dict[str, Any]:
        meta = current_step()
        entry = {
            "id": uuid.uuid4().hex[:8],
            "scene": self.scene,
            "db": db,
            "collection": collection,
            "operation": operation,
            "source": meta.get("source") or "bank",
            "label": meta.get("label") or f"{collection}.{operation}",
            "mongosh": mongosh,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "result_count": result_count,
            "note": note,
        }
        with self._lock:
            self._entries.append(entry)
        print(f"  {collection}.{operation:<11} {entry['latency_ms']:>6} ms  {entry['label']}")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def snapshot(self, *, cluster: str = "local seed", mode: str = "local") -> dict[str, Any]:
        queries = self.entries()
        return {
            "db": "harbourline",
            "cluster": cluster,
            "mode": mode,
            "scene": self.scene,
            "title": self.title,
            "count": len(queries),
            "queries": queries,
        }
