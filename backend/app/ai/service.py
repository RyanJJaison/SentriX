"""
SentriX AI orchestration: system prompt + trimmed history + structured context
-> provider -> bounded tool loop (RBAC-checked) -> answer + sources + actions.

The engine never sees FastAPI/JWT internals — it is handed an already-
authenticated `UserPublic`. Tool output is fenced as untrusted data.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict

from app.ai.models import (
    AIAction,
    AIContext,
    AISource,
    ChatResponse,
    ChatTurn,
    ProviderToolCall,
)
from app.ai.prompt import SYSTEM_PROMPT, render_context, wrap_untrusted
from app.ai.provider import ProviderError, get_provider
from app.ai.tools import execute_tool, tool_schemas
from app.core.config import settings
from app.models.schemas import UserPublic
from app.services import audit_service

logger = logging.getLogger("ai.service")

_MAX_CONVERSATIONS = 500
_CONVERSATION_TTL_S = 60 * 60


class _ConversationStore:
    """Per-process, bounded, TTL'd. Swap for Redis/DB later without touching callers."""

    def __init__(self) -> None:
        self._data: OrderedDict[str, tuple[float, list[ChatTurn]]] = OrderedDict()

    def get(self, cid: str) -> list[ChatTurn]:
        item = self._data.get(cid)
        if not item:
            return []
        ts, turns = item
        if time.time() - ts > _CONVERSATION_TTL_S:
            self._data.pop(cid, None)
            return []
        return turns

    def put(self, cid: str, turns: list[ChatTurn]) -> None:
        self._data[cid] = (time.time(), turns[-(2 * settings.ai_history_limit):])
        self._data.move_to_end(cid)
        while len(self._data) > _MAX_CONVERSATIONS:
            self._data.popitem(last=False)

    def clear(self, cid: str) -> None:
        self._data.pop(cid, None)


_store = _ConversationStore()


def _context_dict(context: AIContext | None, user: UserPublic) -> dict:
    if context is None:
        base: dict = {}
    else:
        base = context.model_dump(exclude_none=True)
        base.pop("user_role", None)  # trust the JWT, not the client
    base["authenticated_role"] = user.role
    return base


async def chat(
    user: UserPublic,
    message: str,
    conversation_id: str | None,
    context: AIContext | None,
) -> ChatResponse:
    provider = get_provider()
    cid = conversation_id or uuid.uuid4().hex

    turns: list[ChatTurn] = [ChatTurn(role="system", content=SYSTEM_PROMPT)]
    ctx_block = render_context(_context_dict(context, user))
    if ctx_block:
        turns.append(ChatTurn(role="system", content=ctx_block))
    turns.extend(_store.get(cid)[-2 * settings.ai_history_limit:])
    turns.append(ChatTurn(role="user", content=message))

    schemas = tool_schemas(user.role)
    sources: list[AISource] = []
    actions: list[AIAction] = []
    tools_used: list[str] = []
    final_text = ""

    for _ in range(settings.ai_max_tool_calls + 1):
        try:
            result = await provider.generate(turns, schemas)
        except ProviderError as exc:
            logger.warning("AI provider error: %s", exc)
            final_text = (
                "I couldn't reach the SentriX intelligence service. Please try again."
            )
            _audit(user, cid, tools_used, actions, ok=False)
            return ChatResponse(
                conversation_id=cid, message=final_text, sources=sources,
                actions=actions, provider=provider.name,
            )

        if not result.tool_calls:
            final_text = result.text or "I don't have anything to add on that."
            break

        turns.append(ChatTurn(role="assistant", content=result.text or "", tool_calls=result.tool_calls))
        for call in result.tool_calls:
            out = execute_tool(call.name, call.arguments, user)
            tools_used.append(call.name)
            turns.append(
                ChatTurn(role="tool", name=call.name, tool_call_id=call.id,
                         content=wrap_untrusted(call.name, out))
            )
            _collect(call, out, sources, actions)
    else:
        final_text = (
            "I've gathered what I can within the tool-call limit. "
            + (final_text or "Ask a more specific follow-up and I'll dig further.")
        )

    turns.append(ChatTurn(role="assistant", content=final_text))
    _store.put(cid, turns[3:] if ctx_block else turns[2:])  # drop system turns from history
    _audit(user, cid, tools_used, actions, ok=True)

    return ChatResponse(
        conversation_id=cid, message=final_text, sources=sources,
        actions=_dedupe_actions(actions), provider=provider.name,
    )


def _collect(
    call: ProviderToolCall, out: dict, sources: list[AISource], actions: list[AIAction]
) -> None:
    if not out.get("ok"):
        return
    if call.name == "emit_action" and isinstance(out.get("action"), dict):
        try:
            actions.append(AIAction(**out["action"]))
        except (TypeError, ValueError):
            logger.debug("dropping malformed action from emit_action")
        return
    ident = (
        call.arguments.get("address")
        or call.arguments.get("txid")
        or call.arguments.get("query")
        or out.get("center")
        or call.name
    )
    sources.append(AISource(type=call.name, id=str(ident)))


def _dedupe_actions(actions: list[AIAction]) -> list[AIAction]:
    seen: set[tuple] = set()
    unique: list[AIAction] = []
    for a in actions:
        key = (a.type, a.target, str(a.payload))
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique[:5]


def _audit(
    user: UserPublic, cid: str, tools_used: list[str], actions: list[AIAction], *, ok: bool
) -> None:
    audit_service.log_system_event(
        "ai_chat",
        (
            f"user={user.username} role={user.role} conversation={cid} "
            f"tools={sorted(set(tools_used))} actions={[a.type for a in actions]} ok={ok}"
        ),
    )


def clear_conversation(conversation_id: str) -> None:
    _store.clear(conversation_id)
