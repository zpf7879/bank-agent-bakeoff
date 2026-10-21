"""Small in-process Mongo stand-in that records every command it runs.

Enough of the driver surface for the Side B bank adapter, the freeze, the
change-stream watcher, and the Scene 2 audit `$lookup`. No server required.
"""
from __future__ import annotations

import copy
import re
import time
import uuid
from typing import Any

from query_log import QueryLog, pretty


def _get(doc: dict[str, Any], path: str) -> tuple[Any, bool]:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _set(doc: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def matches(doc: dict[str, Any], filt: dict[str, Any] | None) -> bool:
    if not filt:
        return True
    for key, expected in filt.items():
        if key == "$or":
            if not any(matches(doc, clause) for clause in expected):
                return False
            continue
        if key == "$and":
            if not all(matches(doc, clause) for clause in expected):
                return False
            continue
        actual, found = _get(doc, key)
        if isinstance(expected, dict) and any(str(op).startswith("$") for op in expected):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$exists" in expected and found != bool(expected["$exists"]):
                return False
            if "$regex" in expected:
                flags = re.IGNORECASE if "i" in str(expected.get("$options", "")) else 0
                if not isinstance(actual, str) or re.search(expected["$regex"], actual, flags) is None:
                    return False
            continue
        if actual != expected:
            return False
    return True


def _project(doc: dict[str, Any], spec: dict[str, Any] | None) -> dict[str, Any]:
    if not spec:
        return copy.deepcopy(doc)
    if set(spec) <= {"_id"} and spec.get("_id") == 0:
        out = copy.deepcopy(doc)
        out.pop("_id", None)
        return out
    out: dict[str, Any] = {}
    if spec.get("_id", 1) != 0 and "_id" in doc:
        out["_id"] = doc["_id"]
    for key, val in spec.items():
        if key == "_id":
            continue
        if val == 0:
            continue
        if val == 1:
            if key in doc:
                out[key] = copy.deepcopy(doc[key])
            continue
        resolved, _ = _get(doc, val[1:]) if isinstance(val, str) and val.startswith("$") else (val, True)
        out[key] = copy.deepcopy(resolved)
    return out


def _sort(docs: list[dict[str, Any]], sort: list[tuple[str, int]]) -> list[dict[str, Any]]:
    out = list(docs)
    for field, direction in reversed(sort):
        present = [d for d in out if _get(d, field)[1]]
        missing = [d for d in out if not _get(d, field)[1]]
        present.sort(key=lambda d, field=field: _get(d, field)[0], reverse=direction < 0)
        out = present + missing
    return out


class LocalCollection:
    def __init__(self, name: str, log: QueryLog, docs: list[dict[str, Any]] | None = None):
        self.name = name
        self._log = log
        self.docs: list[dict[str, Any]] = docs if docs is not None else []

    def _record(self, operation: str, mongosh: str, result_count: int | None, started: float, note: str | None = None) -> None:
        self._log.add(
            collection=self.name,
            operation=operation,
            mongosh=mongosh,
            result_count=result_count,
            started=started,
            note=note,
        )

    def find(self, filt: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        started = time.perf_counter()
        rows = [_project(doc, projection) for doc in self.docs if matches(doc, filt)]
        shell = f"db.{self.name}.find(\n{pretty(filt or {})}"
        if projection:
            shell += f",\n{pretty(projection)}"
        shell += "\n)"
        self._record("find", shell, len(rows), started)
        return rows

    def find_one(
        self,
        filt: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        rows = [doc for doc in self.docs if matches(doc, filt)]
        if sort:
            rows = _sort(rows, sort)
        found = _project(rows[0], projection) if rows else None
        if sort:
            shell = f"db.{self.name}.find(\n{pretty(filt or {})}"
            if projection:
                shell += f",\n{pretty(projection)}"
            shell += f"\n).sort({pretty(dict(sort))}).limit(1)"
            operation = "find"
        else:
            shell = f"db.{self.name}.findOne(\n{pretty(filt or {})}"
            if projection:
                shell += f",\n{pretty(projection)}"
            shell += "\n)"
            operation = "findOne"
        self._record(operation, shell, 1 if found else 0, started)
        return found

    def insert_one(self, document: dict[str, Any]) -> None:
        started = time.perf_counter()
        stored = copy.deepcopy(document)
        stored.setdefault("_id", uuid.uuid4().hex[:12])
        self.docs.append(stored)
        self._record("insertOne", f"db.{self.name}.insertOne(\n{pretty(document)}\n)", 1, started)

    def update_one(self, filt: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        started = time.perf_counter()
        if set(update) - {"$set"}:
            raise NotImplementedError(f"unsupported update operators: {set(update)}")
        matched = next((doc for doc in self.docs if matches(doc, filt)), None)
        if matched is None and upsert:
            matched = {}
            for key, val in filt.items():
                if not isinstance(val, dict):
                    _set(matched, key, copy.deepcopy(val))
            matched["_id"] = uuid.uuid4().hex[:12]
            self.docs.append(matched)
        if matched is not None:
            for key, val in update.get("$set", {}).items():
                _set(matched, key, copy.deepcopy(val))
        shell = f"db.{self.name}.updateOne(\n{pretty(filt)},\n{pretty(update)}"
        if upsert:
            shell += f",\n{pretty({'upsert': True})}"
        shell += "\n)"
        self._record("updateOne", shell, 1 if matched is not None else 0, started)

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        started = time.perf_counter()
        docs = [copy.deepcopy(doc) for doc in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [doc for doc in docs if matches(doc, stage["$match"])]
            elif "$lookup" in stage:
                spec = stage["$lookup"]
                foreign = self._log_db()[spec["from"]].docs
                joined_docs = []
                for doc in docs:
                    joined = [
                        copy.deepcopy(other)
                        for other in foreign
                        if other.get(spec["foreignField"]) == doc.get(spec["localField"])
                    ]
                    for sub in spec.get("pipeline", []):
                        if "$match" not in sub:
                            raise NotImplementedError("lookup pipeline only supports $match")
                        joined = [other for other in joined if matches(other, sub["$match"])]
                    doc[spec["as"]] = joined
                    joined_docs.append(doc)
                docs = joined_docs
            elif "$unwind" in stage:
                path = stage["$unwind"][1:]
                unwound = []
                for doc in docs:
                    for item in doc.get(path) or []:
                        clone = copy.deepcopy(doc)
                        clone[path] = item
                        unwound.append(clone)
                docs = unwound
            elif "$project" in stage:
                docs = [_project(doc, stage["$project"]) for doc in docs]
            else:
                raise NotImplementedError(f"unsupported stage: {stage}")
        note = None
        if any("$lookup" in stage for stage in pipeline):
            if docs and isinstance(docs[0].get("memory"), str):
                note = "Hit: " + docs[0]["memory"][:160]
            elif not docs:
                note = "No match. Held customers have no live offer memory left."
        self._record("aggregate", f"db.{self.name}.aggregate(\n{pretty(pipeline)}\n)", len(docs), started, note)
        return docs

    def watch(self, pipeline: list[dict[str, Any]], full_document: str | None = None) -> None:
        started = time.perf_counter()
        options = {"fullDocument": full_document} if full_document else {}
        shell = f"db.{self.name}.watch(\n{pretty(pipeline)}"
        if options:
            shell += f",\n{pretty(options)}"
        shell += "\n)"
        self._record("watch", shell, None, started, "Listener registered. The freeze above is the event it is waiting for.")

    def _log_db(self) -> LocalDatabase:
        db = getattr(self, "_database", None)
        if db is None:
            raise RuntimeError("collection is not attached to a database")
        return db


class LocalDatabase:
    def __init__(self, log: QueryLog, name: str = "harbourline"):
        self.name = name
        self.log = log
        self._cols: dict[str, LocalCollection] = {}

    def __getitem__(self, name: str) -> LocalCollection:
        col = self._cols.get(name)
        if col is None:
            col = LocalCollection(name, self.log)
            col._database = self
            self._cols[name] = col
        return col

    def __getattr__(self, name: str) -> LocalCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def drop_all(self) -> None:
        self._cols.clear()

    def seed_docs(self, name: str, docs: list[dict[str, Any]]) -> None:
        col = self[name]
        col.docs = [copy.deepcopy(doc) for doc in docs]
