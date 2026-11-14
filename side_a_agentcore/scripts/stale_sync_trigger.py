"""Install, switch on/off, or check the Scene 2 Aurora trigger (Side A stale-memory pipeline).

The trigger calls the Lambda card-agent-stale-sync whenever an account's status changes,
so AgentCore Memory forgets offers for a frozen card.

Usage (after `set -a; source .env; set +a`; connects with the same BANK_PG_* settings as seeding):
  python side_a_agentcore/scripts/stale_sync_trigger.py install   # create it, left OFF
  python side_a_agentcore/scripts/stale_sync_trigger.py on
  python side_a_agentcore/scripts/stale_sync_trigger.py off
  python side_a_agentcore/scripts/stale_sync_trigger.py status

`install` fills the region and account into stale_sync/aurora_trigger.sql and runs it. Connect as
the cluster's master user: creating the aws_lambda extension needs rds_superuser.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "side_a_agentcore" / "app" / "card_agent"))

from bank_aurora import connect  # noqa: E402

SQL_FILE = ROOT / "side_a_agentcore" / "stale_sync" / "aurora_trigger.sql"
TRIGGER = "accounts_status_to_memory"
FUNCTION = "card-agent-stale-sync"


def aws_region_and_account() -> tuple[str, str]:
    import boto3

    session = boto3.Session()
    region = session.region_name or os.environ.get("AWS_REGION")
    if not region:
        sys.exit("No AWS region. Set AWS_REGION / AWS_DEFAULT_REGION.")
    account = session.client("sts").get_caller_identity()["Account"]
    try:
        session.client("lambda", region_name=region).get_function(FunctionName=FUNCTION)
    except Exception as e:  # noqa: BLE001 - only a warning
        print(f"Warning: could not find Lambda {FUNCTION} in {region} ({e.__class__.__name__}). "
              "The trigger will be created, but its calls fail until the Lambda exists.")
    return region, account


def trigger_state(conn) -> str | None:
    row = conn.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgname = %s AND tgrelid = 'accounts'::regclass",
        (TRIGGER,),
    ).fetchone()
    if row is None:
        return None
    return "OFF" if row[0] == "D" else "ON"


def set_enabled(conn, enabled: bool) -> None:
    if trigger_state(conn) is None:
        sys.exit(f"Trigger {TRIGGER} is not installed. Run `install` first.")
    conn.execute(f"ALTER TABLE accounts {'ENABLE' if enabled else 'DISABLE'} TRIGGER {TRIGGER}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["install", "on", "off", "status"])
    args = p.parse_args()

    if args.action == "install":
        region, account = aws_region_and_account()
        sql = SQL_FILE.read_text(encoding="utf-8").replace("<region>", region).replace("<account-id>", account)

    with connect() as conn:
        if args.action == "install":
            conn.execute(sql)
            set_enabled(conn, False)  # Scene 2 starts with the pipeline off
            print(f"Installed {TRIGGER} -> arn:aws:lambda:{region}:{account}:function:{FUNCTION}")
        elif args.action in ("on", "off"):
            set_enabled(conn, args.action == "on")
        state = trigger_state(conn)
        print(f"Trigger {TRIGGER}: {state or 'not installed'}")


if __name__ == "__main__":
    main()
