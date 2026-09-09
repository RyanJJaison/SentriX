"""
Native Google Gemini provider (`v1beta/models/{model}:generateContent`).

Preferred over the OpenAI-compat path for Gemini because the current "thinking"
models return a `thoughtSignature` with every function call that must be echoed
back verbatim on the next turn — a first-class field here, dropped by the compat
shim. One `generate()` = one POST (with a short 5xx retry); the service runs the
tool loop. AI_API_KEY is read from settings and never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.ai.models import ChatTurn, ProviderResult, ProviderToolCall
from app.ai.provider import ProviderError
from app.core.config import settings

logger = logging.getLogger("ai.gemini")

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 2
# Per-attempt read cap. Gemini's endpoint sometimes hangs; a short cap + one
# retry on a fresh connection recovers a transient blip, and the whole budget
# still lands inside the caller's (and the Next dev proxy's ~30s) window so a
# real outage surfaces as the graceful "couldn't reach" message, not a hang.
_ATTEMPT_TIMEOUT_S = 12.0


def _native_base() -> str:
    base = settings.ai_base_url.rstrip("/")
    if base.endswith("/openai"):  # tolerate an OpenAI-compat base URL
        base = base[: -len("/openai")]
    return base or "https://generativelanguage.googleapis.com/v1beta"


def _tool_response_obj(content: str) -> dict:
    """Gemini wants functionResponse.response as an object; keep the untrusted
    fencing intact by passing the wrapped string through untouched."""
    return {"result": content}


def _build(turns: list[ChatTurn]) -> tuple[list[dict], list[dict]]:
    system_parts: list[dict] = []
    contents: list[dict] = []
    for t in turns:
        if t.role == "system":
            if t.content:
                system_parts.append({"text": t.content})
        elif t.role == "user":
            contents.append({"role": "user", "parts": [{"text": t.content}]})
        elif t.role == "assistant":
            parts: list[dict] = []
            if t.content:
                parts.append({"text": t.content})
            for tc in t.tool_calls:
                part: dict = {
                    "functionCall": {"name": tc.name, "args": tc.arguments or {}}
                }
                if tc.thought_signature:
                    part["thoughtSignature"] = tc.thought_signature
                parts.append(part)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        elif t.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": t.name or "tool",
                                "response": _tool_response_obj(t.content),
                            }
                        }
                    ],
                }
            )
    return system_parts, contents


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        self._url = (
            f"{_native_base()}/models/{settings.ai_model}:generateContent"
        )

    async def generate(
        self, turns: list[ChatTurn], tools: list[dict]
    ) -> ProviderResult:
        system_parts, contents = _build(turns)

        gen_config: dict = {
            "temperature": settings.ai_temperature,
            "maxOutputTokens": settings.ai_max_tokens,
        }
        if settings.ai_thinking_budget >= 0:
            gen_config["thinkingConfig"] = {
                "thinkingBudget": settings.ai_thinking_budget
            }

        payload: dict = {"contents": contents, "generationConfig": gen_config}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        _strip_schema(t["function"]) for t in tools if "function" in t
                    ]
                }
            ]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        resp = await self._post(payload)

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError("AI provider returned a non-JSON response") from exc

        if data.get("promptFeedback", {}).get("blockReason"):
            raise ProviderError("AI request was blocked by the safety filter")

        candidates = data.get("candidates") or []
        if not candidates:
            return ProviderResult(text="", tool_calls=[])

        parts = candidates[0].get("content", {}).get("parts") or []
        text_bits: list[str] = []
        calls: list[ProviderToolCall] = []
        for p in parts:
            if isinstance(p.get("text"), str):
                text_bits.append(p["text"])
            fc = p.get("functionCall")
            if isinstance(fc, dict) and fc.get("name"):
                calls.append(
                    ProviderToolCall(
                        id=f"call_{len(calls)}",
                        name=fc["name"],
                        arguments=fc.get("args") or {},
                        thought_signature=p.get("thoughtSignature"),
                    )
                )

        return ProviderResult(text="".join(text_bits).strip(), tool_calls=calls)

    async def _post(self, payload: dict) -> httpx.Response:
        last_status = 0
        per_attempt = min(settings.ai_timeout_seconds, _ATTEMPT_TIMEOUT_S)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=per_attempt) as client:
                    resp = await client.post(
                        self._url,
                        json=payload,
                        headers={"x-goog-api-key": settings.ai_api_key},
                    )
            except httpx.TimeoutException as exc:
                last_status = 0
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Gemini timeout (attempt %s/%s), retrying",
                        attempt,
                        _MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(0.5 * attempt)
                    continue
                raise ProviderError("AI request timed out") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"AI request failed: {type(exc).__name__}"
                ) from exc

            if resp.status_code < 400:
                return resp
            last_status = resp.status_code
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "Gemini HTTP %s (attempt %s/%s), retrying",
                    resp.status_code,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                await asyncio.sleep(0.6 * attempt)
                continue
            logger.error("Gemini returned HTTP %s", resp.status_code)
            raise ProviderError(f"AI provider returned HTTP {resp.status_code}")

        raise ProviderError(f"AI provider returned HTTP {last_status}")


def _strip_schema(fn: dict) -> dict:
    """Gemini's functionDeclarations take a trimmed JSON schema — pass name /
    description / parameters and drop anything OpenAI-specific."""
    out = {"name": fn.get("name", "")}
    if fn.get("description"):
        out["description"] = fn["description"]
    params = fn.get("parameters")
    if isinstance(params, dict):
        out["parameters"] = _clean_params(params)
    return out


def _clean_params(schema: dict) -> dict:
    allowed = {"type", "properties", "required", "items", "enum", "description"}
    out: dict = {}
    for k, v in schema.items():
        if k not in allowed:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _clean_params(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _clean_params(v)
        else:
            out[k] = v
    return out
