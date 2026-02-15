import logging
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from assistant.services import AssistantService
from assistant.services.llm import ChatMessage
from assistant.services.llm.exceptions import LLMConfigurationError, LLMProviderError
from assistant.tools import ToolContext

logger = logging.getLogger(__name__)

CHAT_HISTORY_SESSION_KEY = "assistant_chat_history"
DEFAULT_SYSTEM_PROMPT = "You are Vita's assistant. Keep replies concise and actionable."


def _session_history(request) -> list[dict[str, str]]:
    raw = request.session.get(CHAT_HISTORY_SESSION_KEY, [])
    history: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return history

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if isinstance(role, str) and isinstance(content, str):
            history.append({"role": role, "content": content})
    return history


@require_http_methods(["GET", "POST"])
def chat(request):
    history = _session_history(request)

    if request.method == "POST":
        if request.POST.get("action") == "clear":
            request.session[CHAT_HISTORY_SESSION_KEY] = []
            return redirect("assistant_chat")

        user_message = request.POST.get("message", "").strip()
        if not user_message:
            messages.error(request, "Please enter a message.")
            return redirect("assistant_chat")

        provider_history = [
            ChatMessage(role=entry["role"], content=entry["content"])
            for entry in history
        ]

        service = AssistantService()
        try:
            response = service.reply(
                user_message,
                system_message=DEFAULT_SYSTEM_PROMPT,
                history=provider_history,
                tool_context=ToolContext(user=request.user),
            )
        except LLMConfigurationError as exc:
            logger.error(f"Assistant configuration error: {exc}")
            messages.error(request, f"Assistant misconfigured: {exc}")
            return redirect("assistant_chat")
        except LLMProviderError:
            logger.error("Assistant provider request failed", exc_info=True)
            messages.error(
                request, "Assistant provider request failed. Please try again."
            )
            return redirect("assistant_chat")

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response.content})
        request.session[CHAT_HISTORY_SESSION_KEY] = history
        return redirect("assistant_chat")

    return render(
        request,
        "assistant/chat.html",
        {"messages_history": history},
    )
