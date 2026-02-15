import json
from collections.abc import Mapping
from typing import Any

from ..base import LLMProvider
from ..exceptions import LLMConfigurationError, LLMProviderError
from ..types import ChatMessage, ChatRequest, ChatResponse, TokenUsage, ToolCall


class OpenAIChatGPTProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        client: Any | None = None,
    ):
        if not api_key and client is None:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured for provider 'openai'."
            )

        self.default_model = default_model
        self._error_type: type[Exception] = Exception

        if client is not None:
            self.client = client
            return

        try:
            from openai import OpenAI, OpenAIError
        except ImportError as exc:
            raise LLMConfigurationError(
                "The 'openai' package is required. Add it to dependencies."
            ) from exc

        self.client = OpenAI(api_key=api_key)
        self._error_type = OpenAIError

    def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.default_model
        payload = [self._serialize_message(message) for message in request.messages]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
        }
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            kwargs["max_completion_tokens"] = request.max_output_tokens

        try:
            completion = self.client.chat.completions.create(**kwargs)
        except self._error_type as exc:
            raise LLMProviderError("OpenAI request failed.") from exc

        first_choice = completion.choices[0].message if completion.choices else None
        content = self._coerce_content(first_choice.content if first_choice else "")
        tool_calls = self._parse_tool_calls(
            getattr(first_choice, "tool_calls", None) if first_choice else None
        )
        usage = self._parse_usage(getattr(completion, "usage", None))

        return ChatResponse(
            provider=self.name,
            model=getattr(completion, "model", model),
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            raw=completion,
        )

    def _serialize_message(self, message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }

        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]

        if message.role == "tool":
            if message.tool_call_id:
                payload["tool_call_id"] = message.tool_call_id
            if message.name:
                payload["name"] = message.name

        return payload

    def _parse_usage(self, usage: Any | None) -> TokenUsage | None:
        if usage is None:
            return None

        return TokenUsage(
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    def _coerce_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(self._extract_content_piece(piece) for piece in content).strip()
        return str(content)

    def _parse_tool_calls(self, calls: Any) -> list[ToolCall] | None:
        if not calls:
            return None

        parsed: list[ToolCall] = []
        for idx, call in enumerate(calls):
            fn = getattr(call, "function", None)
            name = getattr(fn, "name", "")
            if not name:
                continue

            raw_args = getattr(fn, "arguments", "{}")
            arguments = self._parse_tool_arguments(raw_args)
            call_id = getattr(call, "id", None) or f"tool_call_{idx + 1}"
            parsed.append(ToolCall(id=call_id, name=name, arguments=arguments))

        return parsed or None

    def _parse_tool_arguments(self, raw_args: Any) -> dict[str, Any]:
        if isinstance(raw_args, Mapping):
            return dict(raw_args)

        if isinstance(raw_args, str):
            raw_args = raw_args.strip()
            if not raw_args:
                return {}
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                return {"_raw": raw_args}
            if isinstance(parsed, Mapping):
                return dict(parsed)
            return {"value": parsed}

        return {"value": raw_args}

    def _extract_content_piece(self, piece: Any) -> str:
        if isinstance(piece, str):
            return piece

        if isinstance(piece, Mapping):
            return str(piece.get("text", ""))

        text = getattr(piece, "text", "")
        return str(text) if text is not None else ""
