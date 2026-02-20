# Vita

## Tasks

Kanban-style task manager for personal todo items.

Includes a hidden **Backlog** status for tasks that shouldn't show on the board until they're promoted to **To do**.

## Health

Tracks stats and goals related to personal health and fitness. Includes

- weight goal
- exercise tracking

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

## Twilio ConversationRelay

1. Set these environment variables in `.env`:
   - `TWILIO_CONVERSATION_RELAY_WS_URL=wss://<your-public-host>/ws/twilio/conversation-relay/`
   - `TWILIO_AUTH_TOKEN=<your-twilio-auth-token>`
   - `OPENAI_API_KEY=<your-openai-api-key>`
2. In Twilio, point your Voice webhook to:
   - `https://<your-public-host>/assistant/twilio/conversation-relay/twiml/`
3. Twilio will connect to the websocket endpoint and stream caller prompts into the assistant.
