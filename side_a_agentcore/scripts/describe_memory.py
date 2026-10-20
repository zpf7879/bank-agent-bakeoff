"""Inspect the AgentCore memory resource and write app/card_agent/memory_config.json.

The agent needs the memory ID and the namespace each built-in strategy writes to.
Run this after `agentcore deploy`, then deploy again so the file ships with the agent.

Usage:
  python side_a_agentcore/scripts/describe_memory.py --memory-id <id>     # use an existing memory
  python side_a_agentcore/scripts/describe_memory.py --create [--kms-key-arn <arn>]

Also prints the security-relevant settings used in Scene 1 (encryption key, event expiry).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import boto3

OUT = Path(__file__).resolve().parents[1] / "app" / "card_agent" / "memory_config.json"
TYPE_TO_KEY = {"SEMANTIC": "facts", "USER_PREFERENCE": "preferences", "EPISODIC": "episodes"}


def create_memory(ctl, kms_key_arn: str | None) -> str:
    kwargs = dict(
        name="harbourline_card_agent",
        description="Bake-off Side A memory",
        eventExpiryDuration=30,
        memoryStrategies=[
            {"semanticMemoryStrategy": {"name": "Facts", "namespaceTemplates": ["/facts/{actorId}/"]}},
            {"userPreferenceMemoryStrategy": {"name": "Preferences", "namespaceTemplates": ["/preferences/{actorId}/"]}},
            {
                "episodicMemoryStrategy": {
                    "name": "Episodes",
                    "namespaceTemplates": ["/episodes/{actorId}/{sessionId}/"],
                    "reflectionConfiguration": {"namespaceTemplates": ["/episodes/{actorId}/"]},
                }
            },
        ],
    )
    if kms_key_arn:
        kwargs["encryptionKeyArn"] = kms_key_arn
    memory = ctl.create_memory(**kwargs)["memory"]
    print("Creating memory", memory["id"], "...")
    while ctl.get_memory(memoryId=memory["id"])["memory"]["status"] == "CREATING":
        time.sleep(10)
    return memory["id"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--memory-id")
    p.add_argument("--create", action="store_true")
    p.add_argument("--kms-key-arn")
    p.add_argument("--region", default=os.getenv("AWS_REGION", "ap-southeast-1"))
    args = p.parse_args()

    ctl = boto3.client("bedrock-agentcore-control", region_name=args.region)
    memory_id = args.memory_id or (create_memory(ctl, args.kms_key_arn) if args.create else None)
    if not memory_id:
        raise SystemExit("Pass --memory-id (see `agentcore status --type memory`) or --create")

    mem = ctl.get_memory(memoryId=memory_id)["memory"]
    namespaces: dict[str, str] = {}
    for s in mem.get("strategies", []):
        key = TYPE_TO_KEY.get(s.get("type", ""))
        templates = s.get("namespaceTemplates") or s.get("namespaces") or []
        if key and templates:
            # Read at actor level: drop the {sessionId} segment so retrieval spans sessions.
            namespaces[key] = templates[0].replace("{sessionId}/", "")

    OUT.write_text(json.dumps({"memory_id": memory_id, "namespaces": namespaces}, indent=2))
    print(f"Wrote {OUT}")
    print(json.dumps(namespaces, indent=2))
    print("\nScene 1 facts for this memory resource:")
    print("  status              :", mem.get("status"))
    print("  customer-managed key:", mem.get("encryptionKeyArn") or "none (service-managed key)")
    print("  event expiry (days) :", mem.get("eventExpiryDuration"))
    print("  strategies          :", [s.get("type") for s in mem.get("strategies", [])])


if __name__ == "__main__":
    main()
