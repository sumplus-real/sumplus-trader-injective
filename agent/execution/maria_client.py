"""A2A client for Maria's secure execution layer.

Maria contract (verified against Sumplus-maria/maria/agent/skill_inbound.py):

    POST {MARIA_BASE_URL}/api/v2/skill/maria-swap/invoke
    Headers:
        Authorization: Bearer <service token>          # _verify_service_bearer
        X-Calling-Agent-Id: <our agent id>
        X-Delegated-User-Token: <maria-jwt>            # acting-as user; required (requires_user_session)
    Body:
        { "action": "get_quote" | "execute_swap",
          "from_token": "<symbol or address>",
          "to_token":   "<symbol or address>",
          "amount":     "<human readable, e.g. '25'>",
          "chain":      "mantle" | "bsc" | ...,
          "slippage_bps": 50 }
    Response:
        { "success": true, "result": {...}, "request_id": "..." }

    When MARIA_SKILLS_TX_ENABLED is off on the Maria side, execute_swap returns a
    dry-run result: result.executed == false, result.dry_run == true, result.would_send == {...}
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.types import ExecutionResult


class MariaClient:
    def __init__(
        self,
        base_url: str | None = None,
        service_token: str | None = None,
        delegated_user_token: str | None = None,
        agent_id: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.environ["MARIA_BASE_URL"]).rstrip("/")
        self.service_token = service_token or os.environ.get("MARIA_SERVICE_TOKEN", "")
        self.delegated_user_token = delegated_user_token or os.environ.get("MARIA_DELEGATED_USER_TOKEN", "")
        self.agent_id = agent_id or os.environ.get("AGENT_ID", "sumplus-trading-agent")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.service_token}",
            "X-Calling-Agent-Id": self.agent_id,
            "X-Delegated-User-Token": self.delegated_user_token,
            "Content-Type": "application/json",
        }

    async def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api/v2/skill/maria-swap/invoke"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
        # Maria returns structured errors (4xx) — surface them rather than raising opaque.
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = {"error": "http_error", "status": resp.status_code, "body": resp.text}
            raise MariaError(resp.status_code, detail)
        return resp.json()

    async def get_quote(self, chain: str, from_token: str, to_token: str, amount: str,
                        slippage_bps: int = 50) -> dict[str, Any]:
        out = await self._invoke({
            "action": "get_quote",
            "chain": chain, "from_token": from_token, "to_token": to_token,
            "amount": amount, "slippage_bps": slippage_bps,
        })
        return out.get("result", {})

    async def execute_swap(self, chain: str, from_token: str, to_token: str, amount: str,
                           slippage_bps: int = 50) -> ExecutionResult:
        out = await self._invoke({
            "action": "execute_swap",
            "chain": chain, "from_token": from_token, "to_token": to_token,
            "amount": amount, "slippage_bps": slippage_bps,
        })
        result = out.get("result", {})
        return ExecutionResult(
            executed=bool(result.get("executed", False)),
            dry_run=bool(result.get("dry_run", False)),
            detail=result,
        )


class MariaError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f"Maria error {status}: {detail}")
