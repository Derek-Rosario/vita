import json
import logging
from collections.abc import Sequence

from assistant.tools import ToolContext, ToolRegistry, get_default_registry

from .llm import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMProvider,
    LLMProviderError,
    ToolCall,
    ToolSpec,
    get_provider,
)

logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        registry: ToolRegistry | None = None,
        max_tool_rounds: int = 6,
    ):
        self.provider = provider or get_provider()
        self.registry = registry or get_default_registry()
        self.max_tool_rounds = max_tool_rounds

    def reply(
        self,
        user_message: str,
        *,
        system_message: str | None = None,
        history: Sequence[ChatMessage] | None = None,
        tool_context: ToolContext | None = None,
        enable_tools: bool = True,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ChatResponse:
        messages: list[ChatMessage] = []
        if system_message:
            messages.append(ChatMessage(role="system", content=system_message))

        if history:
            messages.extend(history)

        messages.append(ChatMessage(role="user", content=user_message))

        tools = self._build_tool_specs() if enable_tools else None
        tool_calls_executed = False

        for round_number in range(1, self.max_tool_rounds + 1):
            request = ChatRequest(
                messages=messages,
                tools=tools,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            response = self.provider.chat(request)

            if not response.tool_calls:
                if not tool_calls_executed:
                    return response
                return ChatResponse(
                    provider=response.provider,
                    model=response.model,
                    content=response.content,
                    tool_calls=response.tool_calls,
                    usage=response.usage,
                    raw=response.raw,
                    tool_calls_executed=True,
                )
            tool_calls_executed = True

            if tool_context is None:
                raise LLMProviderError(
                    "Tool calls were requested by the model but no tool context was provided."
                )

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                tool_payload = self._execute_tool_call(call=call, context=tool_context)
                messages.append(
                    ChatMessage(
                        role="tool",
                        name=call.name,
                        tool_call_id=call.id,
                        content=json.dumps(tool_payload, default=str),
                    )
                )

            logger.info("Assistant tool round %s completed.", round_number)

        raise LLMProviderError(
            f"Exceeded max tool rounds ({self.max_tool_rounds}) without final response."
        )

    def _build_tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in self.registry.all()
        ]

    def _execute_tool_call(
        self,
        *,
        call: ToolCall,
        context: ToolContext,
    ) -> dict:
        tool = self.registry.get(call.name)
        if tool is None:
            return {
                "ok": False,
                "message": f"Unknown tool '{call.name}'.",
                "data": {"tool_name": call.name},
            }

        try:
            result = tool.handler(call.arguments, context)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool '%s' execution failed", call.name)
            return {
                "ok": False,
                "message": str(exc) or "Tool execution failed.",
                "data": {"tool_name": call.name},
            }

        return result.as_payload()
