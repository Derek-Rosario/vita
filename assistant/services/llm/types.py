from dataclasses import dataclass
from typing import Any, Literal

ChatRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatResponse:
    provider: str
    model: str
    content: str
    usage: TokenUsage | None = None
    raw: Any | None = None
