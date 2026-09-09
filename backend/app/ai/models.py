"""Request/response and internal message models for SentriX AI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.traffic import is_safe_id

ACTION_TYPES = (
    "navigate",
    "open_address",
    "open_transaction",
    "focus_graph_node",
    "filter_risk",
    "open_alert",
)

# Section ids the frontend knows how to scroll to.
NAV_TARGETS = (
    "overview",
    "graph-view",
    "alerts",
    "explainability",
    "activity",
    "risk-overview",
)


class AIContext(BaseModel):
    """Structured, trimmed snapshot of what the user is looking at. All optional."""

    route: str | None = Field(default=None, max_length=120)
    selected_address: str | None = None
    selected_transaction: str | None = None
    selected_node: dict[str, Any] | None = None
    graph_context: dict[str, Any] | None = None
    visible_alert_ids: list[str] | None = None
    user_role: str | None = Field(default=None, max_length=32)  # advisory only

    @field_validator("selected_address", "selected_transaction")
    @classmethod
    def _safe_id(cls, v: str | None) -> str | None:
        return v if (v is None or is_safe_id(v)) else None

    @field_validator("visible_alert_ids")
    @classmethod
    def _trim_ids(cls, v: list[str] | None) -> list[str] | None:
        if not v:
            return v
        return [x for x in v if is_safe_id(x)][:20]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)
    context: AIContext | None = None

    @field_validator("conversation_id")
    @classmethod
    def _safe_conv(cls, v: str | None) -> str | None:
        return v if (v is None or is_safe_id(v)) else None


class AIAction(BaseModel):
    type: Literal[
        "navigate",
        "open_address",
        "open_transaction",
        "focus_graph_node",
        "filter_risk",
        "open_alert",
    ]
    target: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] | None = None


class AISource(BaseModel):
    type: str
    id: str
    label: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    sources: list[AISource] = Field(default_factory=list)
    actions: list[AIAction] = Field(default_factory=list)
    provider: str


class AIStatus(BaseModel):
    enabled: bool
    provider: str
    model: str
    has_api_key: bool
    max_tool_calls: int


# --- internal provider protocol types ------------------------------------- #


@dataclass
class ChatTurn:
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list["ProviderToolCall"] = field(default_factory=list)


@dataclass
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Opaque per-call token some providers (Gemini 3.x "thinking" models) return
    # with a function call and require echoed back on the next turn.
    thought_signature: str | None = None


@dataclass
class ProviderResult:
    text: str
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
