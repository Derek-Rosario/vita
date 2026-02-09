# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vita is a single-user Django personal productivity app with modules for tasks (kanban board), health tracking, journaling, and social contact management (mini-CRM). It uses server-rendered templates with HTMX for interactivity, background jobs via `django-tasks`, and real-time updates via `django-eventstream` SSE.

## Commands

```bash
uv sync                    # Install/sync dependencies
./manage.py migrate        # Run database migrations
./manage.py runserver      # Start dev server (SQLite)
./manage.py db_worker      # Start background task worker
./manage.py enqueue_tasks --task <name>  # Enqueue a background task (e.g., run_routines)
```

**Linting:**
```bash
ruff check .               # Python linting
ruff format .              # Python formatting
djlint --lint .            # Django template linting
djlint --reformat .        # Django template formatting
```

**Testing:**
```bash
./manage.py test                     # Run all tests
./manage.py test tasks               # Run tests for a single app
./manage.py test tasks.tests.MyTest.test_method  # Run a single test
```

**Deployment:** Auto-deploys to Fly.io on push to `main` via GitHub Actions. Production runs Daphne (ASGI), a db_worker process, and supercronic for scheduled tasks.

## Architecture

**Stack:** Python 3.14+, Django 6.0, HTMX, Bootstrap 5, SQLite (dev) / PostgreSQL (prod), uv package manager.

**Django apps:**
- `core` - Shared services (toast/voice helpers, geolocation, auth middleware, TTS API)
- `tasks` - Kanban task board with projects, tags, routines, steps, checklists
- `health` - Fitness/weight tracking (stub)
- `journal` - Daily reflections and mood (stub)
- `social` - Contact management with interaction logging and contact strength calculations
- `notifications` - Web push (pywebpush/VAPID), TTS (ElevenLabs), email (Resend SMTP)
- `api` - REST endpoints with bearer token auth (`VITA_API_KEY`)

**Authentication:** `core.middleware.SuperuserRequiredMiddleware` enforces superuser auth on all non-static routes. API routes use `Authorization: Bearer $VITA_API_KEY`.

**HTMX patterns:** Views check `request.htmx` and return partial HTML fragments from `*/partials/*.html` templates. UI feedback uses `HX-Trigger` headers via two helpers in `core/services.py`:
- `add_toast(response, type, message)` - Toast notifications (success/error/info)
- `add_voice_message(response, message)` - ElevenLabs TTS feedback

**Background tasks:** Defined as functions in each app's `tasks.py`, enqueued via `./manage.py enqueue_tasks --task <name>`. Scheduled tasks run via cron: routine generation (every 15 min), contact strength recalculation (daily 5am), inactivity notifications (hourly 8am-11pm).

**Task model lifecycle:** Statuses are BACKLOG, TODO, ON_DECK, IN_PROGRESS, BLOCKED, MISSED, CANCELLED, DONE. Backlog tasks are hidden from the board until promoted. Routine tasks are auto-generated date-driven via `tasks/services.py:generate_tasks_for_date`. Voice feedback uses randomized phrases from `tasks/voice.py` during state transitions.

**Real-time:** SSE via `django-eventstream` at `/events/`, consumed by `static/js/sse.js`.

**PWA:** Service worker at `static/js/sw.js`, manifest at `static/manifest.json`.
