from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST

from core.voice import (
    DEFAULT_ELEVEN_LABS_MODEL_ID,
    DEFAULT_ELEVEN_LABS_OUTPUT_FORMAT,
    DEFAULT_ELEVEN_LABS_VOICE_ID,
    text_to_speech_stream,
)


def _content_type_for_output_format(output_format: str) -> str:
    if output_format.startswith("mp3_"):
        return "audio/mpeg"
    if output_format.startswith("opus_"):
        return "audio/ogg"
    if output_format.startswith("pcm_"):
        return "application/octet-stream"
    return "application/octet-stream"


def _get_payload(request: HttpRequest) -> dict[str, Any]:
    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type == "application/json":
        try:
            body = request.body.decode("utf-8") if request.body else "{}"
            payload = json.loads(body)
            return payload if isinstance(payload, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    # form-encoded/multipart
    return dict(request.POST.items())


@require_POST
def tts(request: HttpRequest) -> StreamingHttpResponse | JsonResponse:
    """POST JSON or form data with {text: "..."} and returns streaming audio."""

    payload = _get_payload(request)
    text = (payload.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "text_required"}, status=400)

    voice_id = (payload.get("voice_id") or DEFAULT_ELEVEN_LABS_VOICE_ID).strip()
    model_id = (payload.get("model_id") or DEFAULT_ELEVEN_LABS_MODEL_ID).strip()
    output_format = (
        payload.get("output_format") or DEFAULT_ELEVEN_LABS_OUTPUT_FORMAT
    ).strip()

    try:
        audio_iter = text_to_speech_stream(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )
    except Exception:
        # Avoid leaking upstream details.
        return JsonResponse({"error": "tts_failed"}, status=502)

    response = StreamingHttpResponse(
        streaming_content=audio_iter,
        content_type=_content_type_for_output_format(output_format),
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"

    # Helpful default for browsers.
    if response["Content-Type"] == "audio/mpeg":
        response["Content-Disposition"] = 'inline; filename="speech.mp3"'

    return response
