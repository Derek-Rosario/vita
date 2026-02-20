import logging
import re

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, VoiceResponse

from assistant.constants import (
    CHAT_HISTORY_SESSION_KEY,
    TWILIO_CONVERSATION_RELAY_WS_PATH,
    assistant_sse_event_name,
    twilio_approved_call_cache_key,
)
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


@csrf_exempt
@require_http_methods(["GET", "POST"])
def twilio_conversation_relay_twiml(request):
    if not _is_valid_twilio_request(request):
        logger.warning("Rejected Twilio ConversationRelay TwiML webhook: invalid signature.")
        return HttpResponseForbidden("Invalid Twilio signature.")

    if not _is_allowed_twilio_call(request):
        logger.warning(
            "Rejected Twilio ConversationRelay TwiML webhook: number not allowlisted."
        )
        return HttpResponseForbidden("Call not allowed.")

    _mark_twilio_call_approved(request)

    response = VoiceResponse()
    connect = Connect()

    kwargs = {"url": _conversation_relay_ws_url(request)}
    if settings.TWILIO_CONVERSATION_RELAY_LANGUAGE:
        kwargs["language"] = settings.TWILIO_CONVERSATION_RELAY_LANGUAGE
    if settings.TWILIO_CONVERSATION_RELAY_WELCOME_GREETING:
        kwargs["welcome_greeting"] = settings.TWILIO_CONVERSATION_RELAY_WELCOME_GREETING
    connect.conversation_relay(**kwargs)
    response.append(connect)

    return HttpResponse(str(response), content_type="text/xml")


def _conversation_relay_ws_url(request) -> str:
    configured = settings.TWILIO_CONVERSATION_RELAY_WS_URL
    if configured:
        return configured

    scheme = "wss" if request.is_secure() else "ws"
    return f"{scheme}://{request.get_host()}{TWILIO_CONVERSATION_RELAY_WS_PATH}"


def _is_valid_twilio_request(request) -> bool:
    if not settings.TWILIO_VALIDATE_SIGNATURES:
        return True

    signature = request.headers.get("X-Twilio-Signature", "").strip()
    auth_token = (settings.TWILIO_AUTH_TOKEN or "").strip()
    if not signature or not auth_token:
        return False

    validator = RequestValidator(auth_token)
    params = request.POST if request.method == "POST" else request.GET
    return validator.validate(request.build_absolute_uri(), params, signature)


def _is_allowed_twilio_call(request) -> bool:
    allowed_number = _normalize_phone_number(settings.TO_PHONE_NUMBER)
    if not allowed_number:
        return False

    params = request.POST if request.method == "POST" else request.GET
    from_number = _normalize_phone_number(params.get("From", ""))
    to_number = _normalize_phone_number(params.get("To", ""))
    return from_number == allowed_number or to_number == allowed_number


def _normalize_phone_number(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _mark_twilio_call_approved(request) -> None:
    params = request.POST if request.method == "POST" else request.GET
    call_sid = (params.get("CallSid") or "").strip()
    if not call_sid:
        return

    cache.set(
        twilio_approved_call_cache_key(call_sid),
        True,
        timeout=settings.TWILIO_CONVERSATION_RELAY_APPROVED_CALL_TTL_SECONDS,
    )
