# Copilot instructions for Vita

## Big picture architecture

- Django monolith with app modules: `core`, `tasks`, `health`, `journal`, `social`, `notifications`, and `api` (see `vita/settings.py` and `vita/urls.py`).
- Primary UI is server-rendered Django templates with HTMX partials and HX triggers; views commonly return fragments like `tasks/partials/*.html` and use `core.services.add_toast` / `add_voice_message` to emit `HX-Trigger` headers.
- Authentication is locked down to a single-user admin setup via `core.middleware.SuperuserRequiredMiddleware`: non-static requests require auth + superuser, and `/api/*` requires `Authorization: Bearer $VITA_API_KEY` (see `core/middleware.py`).
- Background jobs use `django-tasks` with the database backend (`TASKS` in `vita/settings.py`); task routines are generated in `tasks/services.py`.
- Realtime events are streamed via `django-eventstream` at `/events/` (see `vita/urls.py`).
- Notifications include web push (`notifications/services.py`) and voice/TTS via ElevenLabs (`core/voice.py`).

## Key workflows

- Setup is managed with `uv` (from `README.md`): `uv sync`, copy `.env.example`, run `./manage.py migrate`, `./manage.py createsuperuser`, then `./manage.py runserver`.
- DB is SQLite everywhere (dev and production). Production uses a persistent Fly volume at `/data/db.sqlite3` via the `DB_PATH` env var.

## Project-specific patterns to follow

- HTMX actions: use `add_toast` or `add_voice_message` to push UI feedback, and return partial templates when `request.htmx` is true (see `tasks/views.py`).
- Task lifecycle conventions:
  - Backlog tasks (`TaskStatus.BACKLOG`) are intentionally hidden from the board until promoted (see `tasks/views.py`).
  - Routine task generation is date-driven (`generate_tasks_for_date` in `tasks/services.py`).
- Voice feedback uses randomized phrases in `tasks/voice.py`, which are wired in the task state transitions in `tasks/views.py`.
- Geolocation updates are handled via `core/views.py` and `core.models.LastGeolocation`; keep the POST-only endpoint shape consistent.

## Integrations & external dependencies

- ElevenLabs TTS requires `ELEVEN_LABS_API_KEY` and `ELEVEN_LABS_VOICE_ID` (see `core/voice.py` + settings).
- Web push requires VAPID settings (`WEBPUSH_VAPID_*`) and uses `pywebpush` (see `notifications/services.py`).
- Email uses Resend SMTP settings from `.env` (`DEFAULT_FROM_EMAIL`, `SELF_EMAIL`).

## Where to look for examples

- HTMX + toast/voice triggers: `core/services.py`, `tasks/views.py`.
- Task board + checklist flows: `tasks/views.py` and `tasks/templates/`.
- API endpoints: `api/urls.py` and `core/api.py` (TTS).
