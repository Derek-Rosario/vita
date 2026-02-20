from __future__ import annotations

import json
import logging

from channels.generic.websocket import WebsocketConsumer
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from twilio.request_validator import RequestValidator

from assistant.constants import twilio_approved_call_cache_key
from assistant.prompt import get_voice_system_prompt
from assistant.services import AssistantService
from assistant.services.llm import ChatMessage
from assistant.services.llm.exceptions import LLMConfigurationError, LLMProviderError
from assistant.tools import ToolContext

logger = logging.getLogger(__name__)


class ConversationRelayConsumer(WebsocketConsumer):
    """Twilio ConversationRelay websocket bridge for the assistant."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.assistant_service = AssistantService()
        self.system_prompt = get_voice_system_prompt()
        self.history: list[ChatMessage] = []
        self.call_sid: str = ""
        self.tool_context: ToolContext | None = None
        self.enable_tools = False

    def connect(self):
        if not self._is_valid_twilio_signature():
            logger.warning("Rejected ConversationRelay websocket: invalid signature.")
            self.close(code=4403)
            return
        self.accept()

    def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            logger.warning("ConversationRelay payload was not valid JSON.")
            return

        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return

        if event_type == "setup":
            self._handle_setup(payload)
            return

        if event_type == "prompt":
            self._handle_prompt(payload)
            return

        if event_type == "interrupt":
            self._handle_interrupt(payload)
            return

        if event_type == "error":
            logger.warning("ConversationRelay error event: %s", payload.get("description"))

    def _handle_setup(self, payload: dict) -> None:
        call_sid = payload.get("callSid")
        if isinstance(call_sid, str):
            self.call_sid = call_sid
            if self._is_approved_call(call_sid):
                self.tool_context = self._build_tool_context()
                self.enable_tools = self.tool_context is not None
            else:
                self.tool_context = None
                self.enable_tools = False

    def _handle_prompt(self, payload: dict) -> None:
        voice_prompt = payload.get("voicePrompt")
        if not isinstance(voice_prompt, str):
            return

        user_prompt = voice_prompt.strip()
        if not user_prompt:
            return

        assistant_text = self._generate_assistant_reply(user_prompt)
        self.history.append(ChatMessage(role="user", content=user_prompt))
        self.history.append(ChatMessage(role="assistant", content=assistant_text))
        self._send_text_token(assistant_text, last=True)

    def _handle_interrupt(self, payload: dict) -> None:
        utterance = payload.get("utteranceUntilInterrupt")
        if not isinstance(utterance, str):
            return

        utterance = utterance.strip()
        if not utterance:
            return

        for idx in range(len(self.history) - 1, -1, -1):
            message = self.history[idx]
            if message.role != "assistant":
                continue
            self.history[idx] = ChatMessage(role="assistant", content=utterance)
            logger.info("ConversationRelay interrupt applied for call %s", self.call_sid)
            return

    def _generate_assistant_reply(self, user_prompt: str) -> str:
        try:
            response = self.assistant_service.reply(
                user_message=user_prompt,
                system_message=self.system_prompt,
                history=self.history,
                tool_context=self.tool_context,
                enable_tools=self.enable_tools,
            )
            text = (response.content or "").strip()
            if text:
                return text
            return "I did not catch that. Please try again."
        except LLMConfigurationError as exc:
            logger.error("Assistant is misconfigured for ConversationRelay: %s", exc)
            return "The assistant is not configured right now."
        except LLMProviderError:
            logger.exception("Assistant provider failed for ConversationRelay.")
            return "I hit an issue while thinking. Please say that again."
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected ConversationRelay assistant failure.")
            return "I hit an unexpected issue. Please try again."

    def _send_text_token(self, token: str, *, last: bool) -> None:
        self.send(
            text_data=json.dumps(
                {
                    "type": "text",
                    "token": token,
                    "last": last,
                }
            )
        )

    def _build_tool_context(self) -> ToolContext | None:
        user_id_raw = settings.TWILIO_CONVERSATION_RELAY_ASSISTANT_USER_ID
        user = None
        if user_id_raw:
            try:
                user_id = int(user_id_raw)
            except ValueError:
                logger.warning(
                    "TWILIO_CONVERSATION_RELAY_ASSISTANT_USER_ID must be an integer. Got %r.",
                    user_id_raw,
                )
                return None

            user = get_user_model().objects.filter(pk=user_id).first()
            if user is None:
                logger.warning(
                    "TWILIO_CONVERSATION_RELAY_ASSISTANT_USER_ID %s was not found.", user_id
                )
                return None
        else:
            user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()

        if user is None:
            logger.warning("No user available for Twilio ConversationRelay tool context.")
            return None
        return ToolContext(user=user)

    def _is_approved_call(self, call_sid: str) -> bool:
        return bool(cache.get(twilio_approved_call_cache_key(call_sid)))

    def _is_valid_twilio_signature(self) -> bool:
        if not settings.TWILIO_VALIDATE_SIGNATURES:
            return True

        signature = self._header("x-twilio-signature")
        if not signature:
            return False

        auth_token = (settings.TWILIO_AUTH_TOKEN or "").strip()
        if not auth_token:
            logger.warning("TWILIO_AUTH_TOKEN is empty; cannot validate websocket signature.")
            return False

        url = self._conversation_relay_ws_url()
        validator = RequestValidator(auth_token)
        return validator.validate(url, {}, signature)

    def _conversation_relay_ws_url(self) -> str:
        configured = settings.TWILIO_CONVERSATION_RELAY_WS_URL
        if configured:
            return configured

        host = self._header("host") or "localhost"
        path = self.scope.get("path", "")
        query_string = (self.scope.get("query_string") or b"").decode("utf-8").strip()
        if query_string:
            return f"wss://{host}{path}?{query_string}"
        return f"wss://{host}{path}"

    def _header(self, key: str) -> str:
        key_bytes = key.lower().encode("utf-8")
        for header_key, header_value in self.scope.get("headers", []):
            if header_key == key_bytes:
                return header_value.decode("utf-8")
        return ""
