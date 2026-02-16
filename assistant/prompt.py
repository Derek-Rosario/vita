from __future__ import annotations

from pathlib import Path

from django.conf import settings


def get_system_prompt() -> str:
    # Allow deploy-time override from environment/config.
    configured_prompt = (settings.ASSISTANT_SYSTEM_PROMPT or "").strip()
    if configured_prompt:
        return configured_prompt

    prompt_file = (settings.ASSISTANT_SYSTEM_PROMPT_FILE or "").strip()
    if prompt_file:
        path = Path(prompt_file)
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        if path.exists():
            file_prompt = path.read_text(encoding="utf-8").strip()
            if file_prompt:
                return file_prompt

    return settings.ASSISTANT_SYSTEM_PROMPT_DEFAULT
