from collections.abc import Sequence

from .llm import ChatMessage, ChatRequest, ChatResponse, LLMProvider, get_provider


class AssistantService:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or get_provider()

    def reply(
        self,
        user_message: str,
        *,
        system_message: str | None = None,
        history: Sequence[ChatMessage] | None = None,
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

        request = ChatRequest(
            messages=messages,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        return self.provider.chat(request)
