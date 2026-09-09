"""
OpenAI-compatible chat-completions provider (OpenAI, Azure OpenAI, local
gateways, etc. — set AI_BASE_URL). One `generate()` = one POST; the service
runs the tool loop. AI_API_KEY is read from settings and never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.ai.models import ChatTurn, ProviderResult, ProviderToolCall
from app.ai.provider import ProviderError
from app.core.config import settings

logger = logging.getLogger("ai.openai")

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _to_message(turn: ChatTurn) -> dict:
    if turn.role == "tool":
        return {"role": "tool", "tool_call_id": turn.tool_call_id or turn.name or "call",
                "name": turn.name, "content": turn.content}
    msg: dict = {"role": turn.role, "content": turn.content}
    if turn.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in turn.tool_calls
        ]
        msg["content"] = turn.content or None
    return msg


class OpenAICompatProvider:
    name = "openai"

    def __init__(self) -> None:
        self._url = settings.ai_base_url.rstrip("/") + "/chat/completions"

    async def generate(self, turns: list[ChatTurn], tools: list[dict]) -> ProviderResult:
        payload = {
            "model": settings.ai_model,
            "messages": [_to_message(t) for t in turns],
            "temperature": settings.ai_temperature,
            "max_tokens": settings.ai_max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = await self._post(payload)

        try:
            choice = resp.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError("AI provider returned an unexpected response") from exc

        calls = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ProviderToolCall(id=tc.get("id", "call"), name=fn.get("name", ""), arguments=args))

        return ProviderResult(text=choice.get("content") or "", tool_calls=calls)

    async def _post(self, payload: dict) -> httpx.Response:
        """One POST, with a short retry on rate-limit / 5xx (Groq & friends)."""
        last_status = 0
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=settings.ai_timeout_seconds
                ) as client:
                    resp = await client.post(
                        self._url,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {settings.ai_api_key}"
                        },
                    )
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"AI request failed: {type(exc).__name__}"
                ) from exc

            if resp.status_code < 400:
                return resp
            last_status = resp.status_code
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "AI provider %s HTTP %s (attempt %s/%s), retrying",
                    self.name,
                    resp.status_code,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                await asyncio.sleep(0.6 * attempt)
                continue
            logger.error("AI provider %s returned %s", self.name, resp.status_code)
            raise ProviderError(f"AI provider returned HTTP {resp.status_code}")

        raise ProviderError(f"AI provider returned HTTP {last_status}")
