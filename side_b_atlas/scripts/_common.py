"""Shared helpers for Side B scripts.

Environment:
  MONGODB_URI                 connection string of the cluster linked to Atlas Agent Engine
  BANK_DB                     bank database name (default: harbourline)
  AE_PROJECT_ID               Atlas Agent Engine project ID
  AE_CLIENT_ID, AE_CLIENT_SECRET   service account (agentengine service-account create ...)
  AE_BASE_URL                 default https://agentengine.mongodb.com
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.getenv("AE_BASE_URL", "https://agentengine.mongodb.com")


def seed() -> dict:
    return json.loads((ROOT / "data" / "seed.json").read_text())


def bank_db():
    from pymongo import MongoClient

    return MongoClient(os.environ["MONGODB_URI"], appname="bakeoff-scripts")[os.getenv("BANK_DB", "harbourline")]


def access_token() -> str:
    """Exchange service account credentials for a one-hour access token."""
    resp = httpx.post(
        f"{BASE_URL}/api/v1/oauth/token",
        auth=(os.environ["AE_CLIENT_ID"], os.environ["AE_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def hosted_memory():
    """Memory SDK in hosted mode: same memory service the deployed agent uses."""
    from agent_engine_sdk_memory import Memory

    return Memory(service_account_token=access_token(), project_id=os.environ["AE_PROJECT_ID"])
