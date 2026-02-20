CHAT_HISTORY_SESSION_KEY = "assistant_chat_history"
ASSISTANT_SSE_EVENT_PREFIX = "assistant-message"
TWILIO_CONVERSATION_RELAY_WS_PATH = "/ws/twilio/conversation-relay/"


def assistant_sse_event_name(session_key: str) -> str:
    return f"{ASSISTANT_SSE_EVENT_PREFIX}-{session_key}"
