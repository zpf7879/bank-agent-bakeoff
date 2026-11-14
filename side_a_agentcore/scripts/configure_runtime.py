"""Give the AgentCore runtime its settings and permissions.

Copies the agent settings from the environment (.env) into the runtime entry of
<project>/agentcore/agentcore.json, and writes <project>/app/<runtime>/runtime-policy.json
from side_a_agentcore/runtime-policy.example.json with the placeholders filled in.

The policy grants rds-db:connect for IAM database auth, BatchCreate/BatchDeleteMemoryRecords
(the scaffold's role lacks them) and reads of the /bakeoff/* and /episodes/* namespaces
(the scaffold only allows reads from its own strategy namespaces).

Usage (after `set -a; source .env; set +a`):
  python side_a_agentcore/scripts/configure_runtime.py [--project CardAgentA] [--runtime CardAgent]

Safe to run again: existing envVars with the same name are replaced, others are kept.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POLICY_TEMPLATE = REPO / "side_a_agentcore" / "runtime-policy.example.json"
POLICY_FILE = "runtime-policy.json"

# (name, default). None means required.
ENV_VARS = [
    ("ANTHROPIC_MODEL", None),
    ("MAX_CONTEXT_TOKENS", None),
    ("VERIFY_BEFORE_OFFER", None),
    ("BANK_PG_IAM_AUTH", "true"),
    ("BANK_PG_HOST", None),
    ("BANK_PG_PORT", "5432"),
    ("BANK_PG_DBNAME", "harbourline"),
    ("BANK_PG_USER", "postgres"),
]


def env_values() -> list[dict]:
    values, missing = [], []
    for name, default in ENV_VARS:
        value = os.environ.get(name) or default
        if value is None:
            missing.append(name)
        else:
            values.append({"name": name, "value": value})
    if missing:
        sys.exit(f"Missing in the environment: {', '.join(missing)}. Run `set -a; source .env; set +a` first.")
    return values


def patch_agentcore_json(path: Path, runtime_name: str, values: list[dict]) -> None:
    config = json.loads(path.read_text(encoding="utf-8"))
    runtimes = config.get("runtimes", [])
    runtime = next((r for r in runtimes if r.get("name") == runtime_name), None)
    if runtime is None:
        names = [r.get("name") for r in runtimes]
        sys.exit(f"No runtime named {runtime_name!r} in {path} (found: {names}). Use --runtime.")

    ours = {v["name"] for v in values}
    runtime["envVars"] = [v for v in runtime.get("envVars", []) if v.get("name") not in ours] + values
    policies = runtime.setdefault("additionalPolicies", [])
    if POLICY_FILE not in policies:
        policies.append(POLICY_FILE)

    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {path}: {len(values)} envVars, additionalPolicies={policies}")


def cluster_resource_id(rds, host: str) -> str:
    for page in rds.get_paginator("describe_db_clusters").paginate():
        for cluster in page["DBClusters"]:
            if host in (cluster.get("Endpoint"), cluster.get("ReaderEndpoint")):
                return cluster["DbClusterResourceId"]
    sys.exit(f"No Aurora cluster in this account/region has endpoint {host}. Check BANK_PG_HOST and AWS_REGION.")


def write_policy(path: Path) -> None:
    import boto3

    session = boto3.Session()
    region = session.region_name or os.environ.get("AWS_REGION")
    if not region:
        sys.exit("No AWS region. Set AWS_REGION / AWS_DEFAULT_REGION.")
    account = session.client("sts").get_caller_identity()["Account"]
    resource_id = cluster_resource_id(session.client("rds", region_name=region), os.environ["BANK_PG_HOST"])
    db_user = os.environ.get("BANK_PG_USER") or "postgres"

    text = POLICY_TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in {
        "<region>": region,
        "<account-id>": account,
        "<cluster-resource-id>": resource_id,
        "<db-user>": db_user,
    }.items():
        text = text.replace(placeholder, value)
    json.loads(text)  # sanity check
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path} (region {region}, account {account}, cluster {resource_id}, db user {db_user})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default="CardAgentA", help="AgentCore project directory (default: CardAgentA)")
    p.add_argument("--runtime", default="CardAgent", help="runtime name in agentcore.json (default: CardAgent)")
    p.add_argument("--skip-policy", action="store_true", help="only patch agentcore.json")
    args = p.parse_args()

    project = Path(args.project)
    config_path = project / "agentcore" / "agentcore.json"
    if not config_path.exists():
        sys.exit(f"{config_path} not found. Run `agentcore create` first (step 1.3).")

    values = env_values()
    if not args.skip_policy:
        # Resolve AWS details first so a failure leaves agentcore.json untouched.
        code_dir = project / "app" / args.runtime
        code_dir.mkdir(parents=True, exist_ok=True)
        write_policy(code_dir / POLICY_FILE)
    patch_agentcore_json(config_path, args.runtime, values)
    print("Next: cd", project, "&& agentcore validate")


if __name__ == "__main__":
    main()
