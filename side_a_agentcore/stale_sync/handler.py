"""Side A, Scene 2: Lambda that removes stale offer memories when an account is put on hold.

Event (from the Aurora trigger): {"customer_id": "C-1001", "status": "frozen"}
Environment: AGENTCORE_MEMORY_ID, AWS_REGION, optional FACT_NAMESPACES (comma-separated templates)

Two kinds of records hold the offer:
  1. Records the agent wrote directly (remember_customer_fact). These carry metadata,
     so we can delete them exactly.
  2. Records a built-in strategy extracted from conversation. These have no link to
     the account row, so the only way to find them is a semantic search on the text,
     with a score threshold. That match is fuzzy by nature.

Deploy notes: package with boto3 >= the version that includes batch_delete_memory_records.
IAM: bedrock-agentcore:ListMemoryRecords, RetrieveMemoryRecords, BatchDeleteMemoryRecords on the memory ARN.
"""
from __future__ import annotations

import json
import os

import boto3

MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
client = boto3.client("bedrock-agentcore", region_name=os.getenv("AWS_REGION", "ap-southeast-1"))
DIRECT_NS = "/bakeoff/facts/{actorId}/"
EXTRACTED_NS = os.getenv("FACT_NAMESPACES", "/facts/{actorId}/,/preferences/{actorId}/").split(",")
OFFER_QUERY = "credit limit increase offer pre-qualified"
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.5"))


def _direct_offer_records(cid: str) -> list[dict]:
    ns = DIRECT_NS.format(actorId=cid)
    found, token = [], None
    while True:
        kwargs = {"memoryId": MEMORY_ID, "namespace": ns, "maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_memory_records(**kwargs)
        for rec in resp.get("memoryRecordSummaries", []):
            kind = ((rec.get("metadata") or {}).get("kind") or {}).get("stringValue")
            if kind == "offer":
                found.append({"memoryRecordId": rec["memoryRecordId"], "namespace": ns})
        token = resp.get("nextToken")
        if not token:
            return found


def _extracted_offer_records(cid: str) -> list[dict]:
    found = []
    for template in EXTRACTED_NS:
        ns = template.strip().format(actorId=cid)
        resp = client.retrieve_memory_records(
            memoryId=MEMORY_ID, namespace=ns, searchCriteria={"searchQuery": OFFER_QUERY, "topK": 10}, maxResults=10
        )
        for rec in resp.get("memoryRecordSummaries", []):
            if float(rec.get("score") or 0) >= SCORE_THRESHOLD:
                found.append({"memoryRecordId": rec["memoryRecordId"], "namespace": ns})
    return found


def lambda_handler(event, _context):
    cid, status = event["customer_id"], event["status"]
    if status == "active":
        return {"customer_id": cid, "deleted": 0, "note": "account active, nothing to do"}

    doomed = _direct_offer_records(cid) + _extracted_offer_records(cid)
    if doomed:
        client.batch_delete_memory_records(memoryId=MEMORY_ID, records=doomed)
    result = {"customer_id": cid, "status": status, "deleted": len(doomed)}
    print(json.dumps(result))
    return result
