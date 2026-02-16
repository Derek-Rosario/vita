import logging

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from assistant.constants import CHAT_HISTORY_SESSION_KEY, assistant_sse_event_name
from assistant.session import ensure_session_key, session_history
from assistant.tasks import schedule_assistant_reply

logger = logging.getLogger(__name__)


@require_GET
def chat(request):
    session_key = ensure_session_key(request)
    return render(
        request,
        "assistant/chat.html",
        {
            "messages_history": session_history(request),
            "assistant_sse_event_name": assistant_sse_event_name(session_key),
        },
    )


@require_POST
def send_message(request):
    user_message = request.POST.get("message", "").strip()
    if not user_message:
        if request.htmx:
            return HttpResponseBadRequest("Please enter a message.")
        messages.error(request, "Please enter a message.")
        return redirect("assistant_chat")

    session_key = ensure_session_key(request)
    history_before = session_history(request)
    updated_history = [*history_before, {"role": "user", "content": user_message}]
    request.session[CHAT_HISTORY_SESSION_KEY] = updated_history

    schedule_assistant_reply(
        user_id=request.user.id,
        session_key=session_key,
        sse_event_name=assistant_sse_event_name(session_key),
        user_message=user_message,
        history_before=history_before,
    )

    if request.htmx:
        return render(
            request,
            "assistant/partials/chat_log_inner.html",
            {"messages_history": updated_history},
        )

    return redirect("assistant_chat")


@require_POST
def clear_chat(request):
    request.session[CHAT_HISTORY_SESSION_KEY] = []

    if request.htmx:
        return render(
            request,
            "assistant/partials/chat_log_inner.html",
            {"messages_history": []},
        )

    return redirect("assistant_chat")
