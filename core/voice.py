from __future__ import annotations

from collections.abc import Iterator

from django.conf import settings
from elevenlabs.client import ElevenLabs


DEFAULT_ELEVEN_LABS_VOICE_ID = settings.ELEVEN_LABS_VOICE_ID
DEFAULT_ELEVEN_LABS_MODEL_ID = "eleven_flash_v2"
DEFAULT_ELEVEN_LABS_OUTPUT_FORMAT = "mp3_44100_128"


def _get_elevenlabs_client() -> ElevenLabs:
    return ElevenLabs(api_key=settings.ELEVEN_LABS_API_KEY)


def text_to_speech_stream(
    *,
    text: str,
    voice_id: str = DEFAULT_ELEVEN_LABS_VOICE_ID,
    model_id: str = DEFAULT_ELEVEN_LABS_MODEL_ID,
    output_format: str = DEFAULT_ELEVEN_LABS_OUTPUT_FORMAT,
) -> Iterator[bytes]:
    """Stream TTS audio chunks from ElevenLabs."""
    client = _get_elevenlabs_client()
    return client.text_to_speech.stream(
        voice_id,
        text=text,
        model_id=model_id,
        output_format=output_format,
    )


def convert_text_to_speech(
    text: str,
    *,
    voice_id: str = DEFAULT_ELEVEN_LABS_VOICE_ID,
    model_id: str = DEFAULT_ELEVEN_LABS_MODEL_ID,
    output_format: str = DEFAULT_ELEVEN_LABS_OUTPUT_FORMAT,
) -> bytes:
    """Convert text to speech using ElevenLabs and return full audio bytes."""
    return b"".join(
        text_to_speech_stream(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )
    )
