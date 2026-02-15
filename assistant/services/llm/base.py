from abc import ABC, abstractmethod

from .types import ChatRequest, ChatResponse


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a chat request to an LLM provider."""
