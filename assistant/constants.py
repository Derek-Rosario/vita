CHAT_HISTORY_SESSION_KEY = "assistant_chat_history"
DEFAULT_SYSTEM_PROMPT = "You are Vita's assistant. Keep replies concise and actionable."
ASSISTANT_SSE_EVENT_PREFIX = "assistant-message"


def assistant_sse_event_name(session_key: str) -> str:
    return f"{ASSISTANT_SSE_EVENT_PREFIX}-{session_key}"
