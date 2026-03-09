CHAT_HISTORY_SESSION_KEY = "assistant_chat_history"
ASSISTANT_SSE_EVENT_PREFIX = "assistant-message"
TWILIO_CONVERSATION_RELAY_WS_PATH = "/ws/twilio/conversation-relay/"
TWILIO_APPROVED_CALL_CACHE_PREFIX = "assistant-twilio-approved-call"


def assistant_sse_event_name(session_key: str) -> str:
    return f"{ASSISTANT_SSE_EVENT_PREFIX}-{session_key}"


def twilio_approved_call_cache_key(call_sid: str) -> str:
    return f"{TWILIO_APPROVED_CALL_CACHE_PREFIX}:{call_sid}"
