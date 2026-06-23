"""DeepSeek-V4-driven decision strategy.

DeepSeek exposes an OpenAI-compatible REST endpoint, so we call it directly with httpx (already a
dependency for the CMC feed) — no extra SDK. Cheap inference is why we picked it for the tick loop.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from agent.brain.base import Brain
from agent.brain.prompt import SYSTEM_PROMPT, build_user_prompt
from agent.types import Decision


class DeepSeekBrain(Brain):
    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.api_key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")

    async def decide(self, snapshot: dict[str, Any], policy_summary: dict[str, Any]) -> Decision:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(snapshot, policy_summary)},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"].get("content") or "{}"
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> Decision:
        data = json.loads(raw)
        side = str(data.get("side", "hold")).lower()
        if side not in ("buy", "sell", "hold"):
            side = "hold"
        return Decision(
            side=side,                                  # type: ignore[arg-type]
            chain=str(data.get("chain", "")).lower(),
            from_token=str(data.get("from_token", "")),
            to_token=str(data.get("to_token", "")),
            amount_usd=float(data.get("amount_usd", 0) or 0),
            confidence=float(data.get("confidence", 0) or 0),
            rationale=str(data.get("rationale", "")),
        )
