from importlib import import_module
import logging
from threading import Thread

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.tasks import task
from django.template.loader import render_to_string
from django_eventstream import send_event

from assistant.constants import CHAT_HISTORY_SESSION_KEY, DEFAULT_SYSTEM_PROMPT
from assistant.services import AssistantService
from assistant.services.llm import ChatMessage
from assistant.services.llm.exceptions import LLMConfigurationError, LLMProviderError
from assistant.tools import ToolContext

logger = logging.getLogger(__name__)


def schedule_assistant_reply(
    *,
    user_id: int,
    session_key: str,
    sse_event_name: str,
    user_message: str,
    history_before: list[dict[str, str]],
):
    mode = getattr(settings, "ASSISTANT_REPLY_EXECUTION_MODE", "thread").strip().lower()

    if mode == "task":
        generate_assistant_reply_task.enqueue(
            user_id=user_id,
            session_key=session_key,
            sse_event_name=sse_event_name,
            user_message=user_message,
            history_before=history_before,
        )
        return

    if mode == "sync":
        generate_assistant_reply(
            user_id=user_id,
            session_key=session_key,
            sse_event_name=sse_event_name,
            user_message=user_message,
            history_before=history_before,
        )
        return

    thread = Thread(
        target=generate_assistant_reply,
        kwargs={
            "user_id": user_id,
            "session_key": session_key,
            "sse_event_name": sse_event_name,
            "user_message": user_message,
            "history_before": history_before,
        },
        daemon=True,
        name=f"assistant-reply-{session_key[:8]}",
    )
    thread.start()


def generate_assistant_reply(
    *,
    user_id: int,
    session_key: str,
    sse_event_name: str,
    user_message: str,
    history_before: list[dict[str, str]],
):
    close_old_connections()
    history_messages = [
        ChatMessage(role=entry["role"], content=entry["content"])
        for entry in history_before
        if isinstance(entry, dict)
        and isinstance(entry.get("role"), str)
        and isinstance(entry.get("content"), str)
    ]

    assistant_text: str
    try:
        user = get_user_model().objects.get(pk=user_id)
        service = AssistantService()
        response = service.reply(
            user_message=user_message,
            system_message=DEFAULT_SYSTEM_PROMPT,
            history=history_messages,
            tool_context=ToolContext(user=user),
        )
        assistant_text = response.content or ""
    except get_user_model().DoesNotExist:
        logger.error("Assistant reply task failed: user %s not found", user_id)
        assistant_text = "I couldn't find your user account for this request."
    except LLMConfigurationError as exc:
        logger.error("Assistant configuration error in background task: %s", exc)
        assistant_text = f"Assistant misconfigured: {exc}"
    except LLMProviderError:
        logger.error("Assistant provider request failed in background task", exc_info=True)
        assistant_text = "Assistant provider request failed. Please try again."
    except Exception:  # noqa: BLE001
        logger.error("Unexpected assistant background task error", exc_info=True)
        assistant_text = "Unexpected assistant error. Please try again."

    assistant_message = {"role": "assistant", "content": assistant_text}
    _append_message_to_session(session_key=session_key, message=assistant_message)

    rendered = render_to_string(
        "assistant/partials/chat_message.html",
        {"msg": assistant_message},
    )
    send_event("events", sse_event_name, rendered, json_encode=False)
    close_old_connections()


@task()
def generate_assistant_reply_task(
    *,
    user_id: int,
    session_key: str,
    sse_event_name: str,
    user_message: str,
    history_before: list[dict[str, str]],
):
    generate_assistant_reply(
        user_id=user_id,
        session_key=session_key,
        sse_event_name=sse_event_name,
        user_message=user_message,
        history_before=history_before,
    )


def _append_message_to_session(*, session_key: str, message: dict[str, str]) -> None:
    engine = import_module(settings.SESSION_ENGINE)
    session_store = engine.SessionStore(session_key=session_key)
    history = session_store.get(CHAT_HISTORY_SESSION_KEY, [])
    if not isinstance(history, list):
        history = []
    history.append(message)
    session_store[CHAT_HISTORY_SESSION_KEY] = history
    session_store.save()
