from django.conf import settings

from .base import LLMProvider
from .exceptions import LLMConfigurationError
from .providers import OpenAIChatGPTProvider


def get_provider(provider_name: str | None = None) -> LLMProvider:
    configured = (provider_name or settings.ASSISTANT_LLM_PROVIDER).strip().lower()

    if configured == "openai":
        return OpenAIChatGPTProvider(
            api_key=settings.OPENAI_API_KEY,
            default_model=settings.ASSISTANT_OPENAI_MODEL,
        )

    raise LLMConfigurationError(
        f"Unsupported ASSISTANT_LLM_PROVIDER '{configured}'. "
        "Currently supported: openai."
    )
