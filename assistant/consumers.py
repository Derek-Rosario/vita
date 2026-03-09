from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from channels.generic.websocket import WebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from twilio.request_validator import RequestValidator

from assistant.constants import twilio_approved_call_cache_key
from assistant.prompt import get_voice_system_prompt
from assistant.services import AssistantService
from assistant.services.llm import ChatMessage, ToolCall
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
        self._openai_client: Any | None = None
        self._openai_error_type: type[Exception] = Exception
        self._configure_openai_streaming()

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

        assistant_text = self._generate_and_send_assistant_reply(user_prompt)
        self.history.append(ChatMessage(role="user", content=user_prompt))
        self.history.append(ChatMessage(role="assistant", content=assistant_text))

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

    def _generate_and_send_assistant_reply(self, user_prompt: str) -> str:
        if self._openai_client is not None:
            return self._stream_reply_with_openai(user_prompt)

        assistant_text = self._generate_assistant_reply(user_prompt)
        self._send_text_token(assistant_text, last=True)
        return assistant_text

    def _stream_reply_with_openai(self, user_prompt: str) -> str:
        messages = self._build_openai_messages(user_prompt)
        tools_payload = self._build_openai_tools_payload()
        max_rounds = self.assistant_service.max_tool_rounds if tools_payload else 1
        final_text = ""

        try:
            for round_number in range(1, max_rounds + 1):
                result = self._stream_openai_round(
                    messages=messages,
                    tools_payload=tools_payload,
                    stream_tokens_to_twilio=True,
                )

                final_text = result["assistant_text"]
                tool_calls = result["tool_calls"]
                if not tool_calls or self.tool_context is None:
                    self._send_text_token("", last=True)
                    return final_text

                messages.append(
                    self._serialize_assistant_tool_calls(
                        content=final_text,
                        tool_calls=tool_calls,
                    )
                )
                for call in tool_calls:
                    tool_payload = self.assistant_service._execute_tool_call(  # noqa: SLF001
                        call=call,
                        context=self.tool_context,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "name": call.name,
                            "tool_call_id": call.id,
                            "content": json.dumps(tool_payload, default=str),
                        }
                    )

                logger.info(
                    "ConversationRelay tool round %s completed for call %s.",
                    round_number,
                    self.call_sid,
                )
        except self._openai_error_type:
            logger.exception("OpenAI streaming failed for ConversationRelay.")
            final_text = "I hit an issue while thinking. Please say that again."
            self._send_text_token(final_text, last=True)
            return final_text
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected ConversationRelay streaming failure.")
            final_text = "I hit an unexpected issue. Please try again."
            self._send_text_token(final_text, last=True)
            return final_text

        logger.error(
            "ConversationRelay exceeded max tool rounds (%s) for call %s.",
            max_rounds,
            self.call_sid,
        )
        final_text = "I couldn't complete that request. Please try again."
        self._send_text_token(final_text, last=True)
        return final_text

    def _stream_openai_round(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_payload: list[dict[str, Any]] | None,
        stream_tokens_to_twilio: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": settings.ASSISTANT_OPENAI_MODEL,
            "messages": messages,
            "stream": True,
        }
        if tools_payload:
            kwargs["tools"] = tools_payload

        stream = self._openai_client.chat.completions.create(**kwargs)
        assistant_text_parts: list[str] = []
        tool_call_fragments: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            token = self._coerce_stream_content_piece(content)
            if token:
                assistant_text_parts.append(token)
                if stream_tokens_to_twilio:
                    self._send_text_token(token, last=False)

            for tool_call in getattr(delta, "tool_calls", None) or []:
                self._accumulate_tool_call_fragment(tool_call_fragments, tool_call)

        return {
            "assistant_text": "".join(assistant_text_parts).strip(),
            "tool_calls": self._parse_stream_tool_calls(tool_call_fragments),
        }

    def _build_openai_messages(self, user_prompt: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in self.history
            if message.role in {"user", "assistant"}
        )
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _build_openai_tools_payload(self) -> list[dict[str, Any]] | None:
        if not self.enable_tools or self.tool_context is None:
            return None

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.assistant_service._build_tool_specs()  # noqa: SLF001
        ]

    def _serialize_assistant_tool_calls(
        self,
        *,
        content: str,
        tool_calls: list[ToolCall],
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in tool_calls
            ],
        }

    def _accumulate_tool_call_fragment(
        self,
        fragments: dict[int, dict[str, Any]],
        tool_call_delta: Any,
    ) -> None:
        index = getattr(tool_call_delta, "index", 0)
        entry = fragments.setdefault(
            index,
            {
                "id": "",
                "name": "",
                "arguments_parts": [],
            },
        )

        call_id = getattr(tool_call_delta, "id", None)
        if isinstance(call_id, str) and call_id:
            entry["id"] = call_id

        function = getattr(tool_call_delta, "function", None)
        if function is None:
            return

        name_piece = getattr(function, "name", None)
        if isinstance(name_piece, str) and name_piece:
            entry["name"] += name_piece

        args_piece = getattr(function, "arguments", None)
        if isinstance(args_piece, str) and args_piece:
            entry["arguments_parts"].append(args_piece)

    def _parse_stream_tool_calls(
        self,
        fragments: dict[int, dict[str, Any]],
    ) -> list[ToolCall] | None:
        if not fragments:
            return None

        tool_calls: list[ToolCall] = []
        for idx in sorted(fragments):
            fragment = fragments[idx]
            name = str(fragment.get("name", "")).strip()
            if not name:
                continue

            raw_args = "".join(fragment.get("arguments_parts", []))
            arguments = self._parse_tool_arguments(raw_args)
            call_id = str(fragment.get("id", "")).strip() or f"tool_call_{idx + 1}"
            tool_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

        return tool_calls or None

    def _parse_tool_arguments(self, raw_args: Any) -> dict[str, Any]:
        if isinstance(raw_args, Mapping):
            return dict(raw_args)

        if isinstance(raw_args, str):
            raw_args = raw_args.strip()
            if not raw_args:
                return {}
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                return {"_raw": raw_args}
            if isinstance(parsed, Mapping):
                return dict(parsed)
            return {"value": parsed}

        return {"value": raw_args}

    def _coerce_stream_content_piece(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: list[str] = []
            for item in content:
                if isinstance(item, str):
                    pieces.append(item)
                    continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    pieces.append(text)
            return "".join(pieces)
        return str(content)

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

    def _configure_openai_streaming(self) -> None:
        if settings.ASSISTANT_LLM_PROVIDER != "openai":
            return
        if not settings.OPENAI_API_KEY:
            return
        try:
            from openai import OpenAI, OpenAIError
        except ImportError:
            logger.exception("Failed importing openai package for ConversationRelay stream.")
            return

        self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._openai_error_type = OpenAIError

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
