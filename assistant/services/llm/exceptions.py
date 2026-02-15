class LLMError(Exception):
    """Base exception for LLM provider failures."""


class LLMConfigurationError(LLMError):
    """Raised when the configured LLM provider is invalid or incomplete."""


class LLMProviderError(LLMError):
    """Raised when an upstream provider request fails."""
