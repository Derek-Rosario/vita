CHAT_HISTORY_SESSION_KEY = "assistant_chat_history"
ASSISTANT_SSE_EVENT_PREFIX = "assistant-message"


def assistant_sse_event_name(session_key: str) -> str:
    return f"{ASSISTANT_SSE_EVENT_PREFIX}-{session_key}"
