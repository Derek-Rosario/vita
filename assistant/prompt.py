from __future__ import annotations

from pathlib import Path

from django.conf import settings


def get_system_prompt() -> str:
    return _resolve_prompt(
        direct_prompt=settings.ASSISTANT_SYSTEM_PROMPT,
        prompt_file=settings.ASSISTANT_SYSTEM_PROMPT_FILE,
        default_prompt=settings.ASSISTANT_SYSTEM_PROMPT_DEFAULT,
    )


def get_voice_system_prompt() -> str:
    return _resolve_prompt(
        direct_prompt=settings.ASSISTANT_VOICE_SYSTEM_PROMPT,
        prompt_file=settings.ASSISTANT_VOICE_SYSTEM_PROMPT_FILE,
        default_prompt=settings.ASSISTANT_VOICE_SYSTEM_PROMPT_DEFAULT,
    )


def _resolve_prompt(
    *,
    direct_prompt: str,
    prompt_file: str,
    default_prompt: str,
) -> str:
    # Allow deploy-time override from environment/config.
    configured_prompt = (direct_prompt or "").strip()
    if configured_prompt:
        return configured_prompt

    prompt_file = (prompt_file or "").strip()
    if prompt_file:
        path = Path(prompt_file)
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        if path.exists():
            file_prompt = path.read_text(encoding="utf-8").strip()
            if file_prompt:
                return file_prompt

    return default_prompt
