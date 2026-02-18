# Vita

## Tasks

Kanban-style task manager for personal todo items.

Includes a hidden **Backlog** status for tasks that shouldn't show on the board until they're promoted to **To do**.

## Health

Tracks stats and goals related to personal health and fitness. Includes

- weight goal
- exercise tracking
- maybe other stuff

## Journal

Tracks daily reflections, mood, etc.

## Social

Tracks contacts including family, friends, acquaintances, and colleagues. A mini-CRM.

# Setup

1. Install `uv`
2. `uv sync`
3. `cp .env.example .env`
4. `./manage.py migrate`
5. `./manage.py createsuperuser`
6. `./manage.py runserver`
