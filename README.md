# Messaging Monitoring System — InboxSignal

> Technical documentation: [`docs/technical-readme.md`](docs/technical-readme.md)

AI-powered Django service for monitoring Telegram communication streams, converting raw messages into structured events, prioritizing what matters, and delivering internal alerts.

## What the project does

The system is built for one core job: reduce message noise and surface only the signals that need attention.

Current MVP flow:

- receives Telegram messages
- stores raw incoming messages in PostgreSQL
- applies rules-based triage
- uses AI selectively for ambiguous messages
- creates structured events with priority
- sends internal alerts to Telegram

This is **not** a chat client and **not** a CRM. It is a message triage and alerting backend with a simple web UI for monitoring profiles and event review.

## Main features

- Django-based web application with dashboard and profile management
- Telegram Bot integration
- webhook-based ingestion with additional `X-Telegram-Bot-Api-Secret-Token` validation
- polling mode for local development
- background processing with Celery + Redis
- rules-first analysis with `optional AI enrichment`
- event creation with priority scoring
- Telegram alert delivery
- customer auto-replies and anti-spam limits
- admin panel for users, profiles, connected sources, AI results, events, and alerts
- Pytest-based test suite

## Tech stack

- Python 3.12
- Django 6
- PostgreSQL 16
- Redis 7
- Celery
- django-allauth
- OpenAI API
- Telegram Bot API
- Docker Compose v2

## Architecture at a glance

```text
Telegram -> Ingestion -> Rules -> Optional AI -> Event -> AlertDelivery -> Telegram alert chat
```

Core domain objects:

```text
User
  -> MonitoringProfile
    -> ConnectedSource
      -> IncomingMessage
        -> Event
          -> AlertDelivery
```

## Local development

### 1. Create environment file

```bash
cp .env.example .env
```

Fill at least:

- `DJANGO_SECRET_KEY`
- `FIELD_ENCRYPTION_KEY`
- PostgreSQL settings
- Redis settings
- `OPENAI_API_KEY` if AI should be enabled

### 2. Start the stack

```bash
docker compose up --build
```

Services:

- `web` — Django development server
- `celery_worker` — background jobs
- `db` — PostgreSQL
- `redis` — broker, cache, rate limits, temporary state

Application URL:

- `http://localhost:8000`

## Migrations

Create migrations:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py makemigrations accounts monitoring integrations ai alerts
```

Apply migrations:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py migrate
```

Show migration state:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py showmigrations
```

## Tests

Run all tests:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest
```

Run one module:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/integrations/test_telegram_webhook.py -q
```

## Telegram integration

### Polling mode (RECOMMENDED)

Use polling for local development when no public HTTPS URL is available.

Disable webhook first:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook delete \
  --source-id 1 \
  --drop-pending-updates
```

Start polling:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 1
```

One-time polling check:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 1 \
  --once
```

---

### Webhook mode

Use webhook mode when you have a public HTTPS URL.

Set webhook:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook set \
  --source-id 1 \
  --base-url https://your-public-domain.example \
  --drop-pending-updates
```

Show webhook info:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook info \
  --source-id 1
```

Delete webhook:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook delete \
  --source-id 1 \
  --drop-pending-updates
```

## Security notes

Current important protections include:

- encrypted storage of connected source credentials
- dedicated webhook path secret
- dedicated Telegram secret token header validation
- webhook rate limits on source and profile level
- customer anti-spam limits
- alert cooldown support
- write-only admin fields for sensitive Telegram secrets

## Admin coverage

Django admin is configured for:

- Users
- Monitoring profiles
- Connected sources
- Incoming messages
- External contacts
- Events
- AI analysis results
- Alert deliveries

## Project status

This repository is currently focused on the Telegram MVP.

Implemented end-to-end:

- profile creation from dashboard
- Telegram source connection
- Telegram ingestion
- AI-assisted analysis
- event creation
- Telegram alert delivery
- review / ignore / escalate / archive workflow

Planned or natural next steps:

- WhatsApp or additional channel adapters
- digest notifications
- richer analytics
- stronger production deployment profile
- operational dashboards and monitoring

## Useful commands

Open Django shell:

```bash
docker compose exec web python manage.py shell
```

Show Celery logs:

```bash
docker compose logs -f celery_worker
```

Run Django checks:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
```

## Contacts

Author: Maksym Petrykin

Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)

Telegram: [@max_p95](https://t.me/max_p95)