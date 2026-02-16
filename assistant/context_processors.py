from __future__ import annotations

from django.http import HttpRequest

from assistant.constants import assistant_sse_event_name
from assistant.session import ensure_session_key, session_history


def assistant_widget(request: HttpRequest) -> dict[str, object]:
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"assistant_widget_enabled": False}

    session_key = ensure_session_key(request)
    return {
        "assistant_widget_enabled": True,
        "assistant_messages_history": session_history(request),
        "assistant_sse_event_name": assistant_sse_event_name(session_key),
    }
