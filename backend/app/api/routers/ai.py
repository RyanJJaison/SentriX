"""
SentriX AI chat endpoint. Same JWT + role gate as the other data endpoints
(admin / investigator / analyst); audit-logged by the middleware in `app.main`.
The browser never sees the LLM key — it talks only to this route.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.ai import service
from app.ai.models import AIStatus, ChatRequest, ChatResponse
from app.api.deps import require_role
from app.core.config import settings
from app.models.schemas import UserPublic

router = APIRouter(prefix="/ai", tags=["ai"])

_ROLES = require_role("admin", "investigator", "analyst")


@router.get("/status", response_model=AIStatus)
def ai_status(user: UserPublic = Depends(_ROLES)) -> AIStatus:
    return AIStatus(
        enabled=settings.ai_enabled,
        provider=settings.ai_provider if (settings.ai_api_key or settings.ai_provider == "mock") else "mock",
        model=settings.ai_model,
        has_api_key=bool(settings.ai_api_key),
        max_tool_calls=settings.ai_max_tool_calls,
    )


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    payload: ChatRequest,
    user: UserPublic = Depends(_ROLES),
) -> ChatResponse:
    if not settings.ai_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SentriX AI is disabled (AI_ENABLED=false).",
        )
    return await service.chat(
        user=user,
        message=payload.message,
        conversation_id=payload.conversation_id,
        context=payload.context,
    )


@router.post("/conversations/{conversation_id}/clear")
def ai_clear(conversation_id: str, user: UserPublic = Depends(_ROLES)) -> Response:
    service.clear_conversation(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
