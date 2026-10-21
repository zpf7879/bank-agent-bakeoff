"""The scene monitor runs Side B's real command shapes against the local seed.

No MongoDB server and no Agent Engine. The mongosh in the log is built from the
arguments the bank adapter and the scene scripts pass. monitor.js, the frontend
plugin, must carry those same commands.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))

from scene_playback import WATCH_PIPELINE, play_scene  # noqa: E402


def _shells(scene: str) -> list[dict]:
    return play_scene(scene)["queries"]


def _joined(queries: list[dict]) -> str:
    return "\n".join(q["mongosh"] for q in queries)


def test_watch_pipeline_matches_stale_watcher() -> None:
    source = (ROOT / "side_b_atlas" / "scripts" / "stale_watcher.py").read_text()
    module = ast.parse(source)
    found = None
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PIPELINE" for t in node.targets):
            segment = ast.get_source_segment(source, node.value)
            found = ast.literal_eval(segment)
    assert found == WATCH_PIPELINE


def test_fraud_freeze_audit_hits_then_clears() -> None:
    queries = _shells("stale")
    shells = _joined(queries)
    assert '"status": "frozen"' in shells
    assert '"hold_reason": "fraud review"' in shells
    assert "db.accounts.watch" in shells
    assert "$lookup" in shells
    audits = [q for q in queries if q["operation"] == "aggregate"]
    assert [q["result_count"] for q in audits] == [1, 0]
    assert "pre-qualified" in (audits[0]["note"] or "")
    assert "No match" in (audits[1]["note"] or "")
    assert "WITHDRAWN" in shells
    assert '"stale": true' in shells


def test_fee_waiver_uses_the_bank_adapter() -> None:
    queries = _shells("procedural")
    shells = _joined(queries)
    labels = " ".join(q["label"] for q in queries)
    assert "discover_procedures" in labels
    assert "get_procedure" in labels
    assert "db.customers.findOne" in shells
    assert "db.accounts.findOne" in shells
    assert "db.fee_waivers.find" in shells
    assert "db.fee_waivers.insertOne" in shells
    assert "LFW-01" in shells
    assert '"late_fee_sgd": 0' in shells


def test_dispute_and_glossary() -> None:
    queries = _shells("taxonomic")
    shells = _joined(queries)
    assert "db.disputes.find" in shells
    assert '"$ne": "closed"' in shells
    assert "provisional credit" in shells
    assert any(q["collection"] == "taxonomic" and q["result_count"] == 1 for q in queries)


def test_context_reads_semantic_and_episodic() -> None:
    queries = _shells("context")
    by_coll = {q["collection"]: q["result_count"] for q in queries}
    assert by_coll["semantic"] == 2
    assert by_coll["episodic"] == 1


def test_frontend_plugin_matches_playback() -> None:
    text = (ROOT / "monitor.js").read_text()
    raw = text.split("/* QUERIES_START */", 1)[1].split("/* QUERIES_END */", 1)[0]
    catalog = json.loads(raw)
    keep = ("db", "collection", "operation", "source", "label", "mongosh", "result_count", "note")
    assert set(catalog) == {"residency", "stale", "procedural", "taxonomic", "context"}
    for scene in catalog:
        live = play_scene(scene)
        expect = [{key: query.get(key) for key in keep} for query in live["queries"]]
        assert catalog[scene]["title"] == live["title"]
        assert catalog[scene]["queries"] == expect


def test_relocation_is_an_upsert() -> None:
    shells = _joined(_shells("residency"))
    assert "db.short_term.insertOne" in shells
    assert "db.semantic.updateOne" in shells
    assert '"upsert": true' in shells
    assert "Melbourne" in shells


if __name__ == "__main__":
    test_watch_pipeline_matches_stale_watcher()
    test_fraud_freeze_audit_hits_then_clears()
    test_fee_waiver_uses_the_bank_adapter()
    test_dispute_and_glossary()
    test_context_reads_semantic_and_episodic()
    test_relocation_is_an_upsert()
    test_frontend_plugin_matches_playback()
    print("ok")
