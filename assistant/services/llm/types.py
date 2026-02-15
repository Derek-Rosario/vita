from dataclasses import dataclass
from typing import Any, Literal

ChatRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: list[ChatMessage]
    tools: list[ToolSpec] | None = None
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatResponse:
    provider: str
    model: str
    content: str
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage | None = None
    raw: Any | None = None
