"""AI provider abstraction. The service talks only to this interface."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from app.ai.models import ChatTurn, ProviderResult
from app.core.config import settings

logger = logging.getLogger("ai.provider")


class AIProvider(Protocol):
    name: str

    async def generate(
        self, turns: list[ChatTurn], tools: list[dict[str, Any]]
    ) -> ProviderResult:
        """One model step: either a final answer (`text`) or `tool_calls` to run."""
        ...


class ProviderError(RuntimeError):
    pass


def get_provider() -> AIProvider:
    provider = settings.ai_provider.strip().lower()

    if provider in ("gemini", "google"):
        if not settings.ai_api_key:
            logger.warning("AI_PROVIDER=%s but AI_API_KEY is empty; using mock provider", provider)
        else:
            from app.ai.providers.gemini import GeminiProvider

            return GeminiProvider()

    if provider in ("openai", "openai_compat", "azure", "compat"):
        if not settings.ai_api_key:
            logger.warning("AI_PROVIDER=%s but AI_API_KEY is empty; using mock provider", provider)
        else:
            from app.ai.providers.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider()

    from app.ai.providers.mock import MockProvider

    return MockProvider()
