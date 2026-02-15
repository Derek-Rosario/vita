from collections.abc import Mapping
from typing import Any

from ..base import LLMProvider
from ..exceptions import LLMConfigurationError, LLMProviderError
from ..types import ChatRequest, ChatResponse, TokenUsage


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
        payload = [{"role": m.role, "content": m.content} for m in request.messages]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
        }
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
        usage = self._parse_usage(getattr(completion, "usage", None))

        return ChatResponse(
            provider=self.name,
            model=getattr(completion, "model", model),
            content=content,
            usage=usage,
            raw=completion,
        )

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

    def _extract_content_piece(self, piece: Any) -> str:
        if isinstance(piece, str):
            return piece

        if isinstance(piece, Mapping):
            return str(piece.get("text", ""))

        text = getattr(piece, "text", "")
        return str(text) if text is not None else ""
