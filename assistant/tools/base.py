from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ToolContext:
    user: Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | list[Any] | str | None = None
    message: str = ""

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.message:
            payload["message"] = self.message
        if self.data is not None:
            payload["data"] = self.data
        return payload


ToolHandler = Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    when_to_use: str = ""
    when_not_to_use: str = ""
