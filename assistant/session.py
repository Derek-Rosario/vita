from __future__ import annotations

from django.http import HttpRequest

from assistant.constants import CHAT_HISTORY_SESSION_KEY


def session_history(request: HttpRequest) -> list[dict[str, str]]:
    raw = request.session.get(CHAT_HISTORY_SESSION_KEY, [])
    if not isinstance(raw, list):
        return []

    history: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if isinstance(role, str) and isinstance(content, str):
            history.append({"role": role, "content": content})
    return history


def ensure_session_key(request: HttpRequest) -> str:
    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key
    if not session_key:
        raise RuntimeError("Unable to initialize session key for assistant chat.")
    return session_key
