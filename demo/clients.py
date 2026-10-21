"""Thin clients that send the same message to both deployed agents.

Side A environment:  SIDE_A_RUNTIME_ARN, AWS_REGION (default ap-southeast-1), AWS credentials
Side B environment:  AE_PROJECT_ID, AE_WORKSPACE_ID, AE_CLIENT_ID, AE_CLIENT_SECRET, AE_BASE_URL (optional)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Reply:
    side: str
    text: str
    elapsed_ms: int
    extra: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class SideA:
    name = "A · AgentCore"

    def __init__(self) -> None:
        import boto3

        self.arn = os.environ["SIDE_A_RUNTIME_ARN"]
        self.client = boto3.client("bedrock-agentcore", region_name=(os.getenv("AWS_REGION") or "ap-southeast-1"))

    def ask(self, message: str, session_id: str, customer_id: str) -> Reply:
        started = time.perf_counter()
        try:
            resp = self.client.invoke_agent_runtime(
                agentRuntimeArn=self.arn,
                runtimeSessionId=session_id,
                payload=json.dumps({"prompt": message, "customer_id": customer_id}).encode(),
            )
            body = json.loads(resp["response"].read())
        except Exception as exc:  # show the error in the demo instead of crashing
            return Reply(self.name, "", int((time.perf_counter() - started) * 1000), error=str(exc))
        return Reply(self.name, body.get("result", ""), int((time.perf_counter() - started) * 1000),
                     extra={k: body.get(k) for k in ("tool_calls", "memory_context_tokens", "memory_sources")})


class SideB:
    name = "B · Atlas Agent Engine"

    def __init__(self) -> None:
        self.base = os.getenv("AE_BASE_URL", "https://agentengine.mongodb.com")
        self.project = os.environ["AE_PROJECT_ID"]
        self.workspace = os.environ["AE_WORKSPACE_ID"]
        self._token: str | None = None
        self._token_at = 0.0

    def _auth(self) -> str:
        if not self._token or time.time() - self._token_at > 3000:  # tokens last one hour
            resp = httpx.post(f"{self.base}/api/v1/oauth/token",
                              auth=(os.environ["AE_CLIENT_ID"], os.environ["AE_CLIENT_SECRET"]),
                              data={"grant_type": "client_credentials"}, timeout=30)
            resp.raise_for_status()
            self._token, self._token_at = resp.json()["access_token"], time.time()
        return self._token

    def ask(self, message: str, session_id: str, customer_id: str) -> Reply:
        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.base}/api/v1/projects/{self.project}/workspaces/{self.workspace}/invoke",
                headers={
                    "Authorization": f"Bearer {self._auth()}",
                    "X-Session-ID": session_id,
                    "X-Mdb-Agent-Engine-Custom-Customer-Id": customer_id,
                },
                json={"message": message, "customer_id": customer_id},
                timeout=180,
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            return Reply(self.name, "", int((time.perf_counter() - started) * 1000), error=str(exc))
        return Reply(self.name, str(body.get("response", "")), int((time.perf_counter() - started) * 1000),
                     extra={"execution_id": body.get("execution_id"), "status": body.get("status")})
