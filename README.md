# Messaging Monitoring System — InboxSignal

> Technical documentation: [`docs/technical-readme.md`](docs/technical-readme.md)

AI-powered Django service for monitoring Telegram and Gmail communication streams, converting raw messages into structured events, prioritizing what matters, and delivering internal alerts and digests.

## What the project does

InboxSignal is built for one operational job: reduce message noise and surface only the signals that need attention.

Current MVP flow:

```text
Telegram Bot -> Ingestion -> Rules -> Optional AI -> Event -> AlertDelivery -> Telegram alert/digest
Gmail        -> Ingestion -> Rules -> Optional AI -> Event -> AlertDelivery -> Telegram alert/digest
```

The system is **not** a chat client and **not** a CRM. It is a message triage backend with a web UI for onboarding, profile configuration, event review, alert setup, digest configuration, and minimal operational visibility.

## Main features

- Django-based web application with dashboard and monitoring profile management
- separate onboarding flow after signup
- scenario presets for common product flows:
  - lead detection
  - complaint / negative feedback
  - booking / request
  - urgent messages
  - general monitoring
  - custom configuration
- full create/edit monitoring profile constructor
- configurable profile behavior:
  - `track_*` signals: leads, complaints, requests, urgent, general activity
  - `ignore_*` noise filters: greetings, short replies, emoji-only messages
  - `urgent_*` rules: negative messages, deadlines, repeated follow-ups
  - `extract_*` fields: name, contact, budget, product/service, date/time
- Telegram Bot integration
- Gmail read-only integration via Google OAuth
- separate Telegram and Gmail monitoring profile creation flows
- Gmail polling via Celery Beat
- Gmail email normalization into `IncomingMessage(channel=email)`
- shared rules-first and optional AI analysis for Telegram and Gmail messages
- webhook-based ingestion with `X-Telegram-Bot-Api-Secret-Token` validation
- polling mode for local development
- protected Telegram bot system commands:
  - `/start`
  - `/start_alerts <setup-token>`
  - `/digest`
- Telegram webhook secrets can be safely rotated with a dedicated management command, preserving the previous secret pair during a short grace period to avoid ingestion downtime in webhook mode.
- rules-first message analysis with optional AI enrichment
- event creation with priority scoring
- instant Telegram alert delivery
- Telegram alert delivery for events created from both Telegram and Gmail sources
- digest notifications for new important/urgent events
- per-profile digest frequency: every 1, 3, 6, 12, or 24 hours
- Celery worker for async processing and alert delivery
- Celery Beat service for scheduled digest building
- idempotent alert and digest delivery creation
- customer auto-replies and anti-spam limits
- AI usage limits per account and optional stricter per-profile limit
- minimal internal ops visibility for failed alerts, AI fallbacks, webhook rejects, and pending retries
- Django admin coverage for core models
- Pytest-based test suite

## Tech stack

- Python 3.12
- Django 6.x
- PostgreSQL 16
- Redis 7
- Celery
- Celery Beat
- django-allauth
- OpenAI API
- Telegram Bot API
- Gmail API
- Google OAuth 2.0
- Docker Compose v2

## Core domain objects

```text
User
  -> MonitoringProfile
    -> ConnectedSource
      -> IncomingMessage
        -> Event
          -> AlertDelivery
        -> AIAnalysisResult
```

Important delivery types:

```text
AlertDelivery.delivery_type = instant | digest
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
- `celery_worker` — background processing and alert delivery
- `celery_beat` — scheduled digest builder
- `db` — PostgreSQL
- `redis` — broker, result backend, cache, rate limits, cooldowns, temporary state

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

Run focused modules:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/integrations/test_telegram_webhook.py -q
```

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/alerts -q
```

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/monitoring/test_ops_visibility.py -q
```

## Telegram integration

### Polling mode for local development

Use polling when no public HTTPS URL is available.

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

### Webhook mode for public HTTPS environments

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

## Gmail integration

Gmail is implemented as a **read-only ingestion adapter**, not as an email client.

MVP scope:

- connect a Gmail account through Google OAuth
- request only the read-only Gmail scope
- read recent INBOX messages
- parse subject, sender, received date, and plain text body
- normalize emails into `IncomingMessage(channel=email)`
- reuse the existing rules-first and optional AI analysis pipeline
- create `Event` records from important or urgent emails
- deliver internal alerts and digests through the configured Telegram alert destination

Out of scope:

- sending emails
- replying from the system
- deleting emails
- changing Gmail labels
- rendering full HTML emails
- processing attachments
- building a full inbox UI

OAuth scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```
Gmail credentials are stored in ConnectedSource.credentials_encrypted.

Only non-sensitive sync state is stored in ConnectedSource.metadata, for example:
```text
{
  "gmail_address": "user@example.com",
  "sync_mode": "polling",
  "label_filter": "INBOX",
  "last_sync_at": "2026-05-01T22:19:46+02:00"
}
```

#### .env.example
```text
# ==============================================================================
# Gmail integration
# ==============================================================================

GMAIL_POLLING_ENABLED=True
GMAIL_POLLING_BEAT_MINUTE=*/5
GMAIL_MAX_MESSAGES_PER_SYNC=20
GMAIL_MAX_BODY_CHARS=8000
GMAIL_OAUTH_SCOPES=https://www.googleapis.com/auth/gmail.readonly
```

### Gmail polling

Gmail sync is handled by Celery Beat.

celery_beat -> sync_gmail_sources_task -> Gmail API -> IncomingMessage -> process_incoming_message_task

### Google OAuth redirect URI

For local development, the Google OAuth client must include this authorized redirect URI:
```text
http://localhost:8000/integrations/gmail/oauth/callback/
```

If the application is opened through 127.0.0.1, add this URI as well:
```text
http://127.0.0.1:8000/integrations/gmail/oauth/callback/
```
---

## Telegram bot commands

### `/start`

Returns a basic bot status message and lists available service commands.

### `/start_alerts <setup-token>`

Binds the current Telegram chat as the internal alert destination.

The setup token is generated when a Telegram source has no configured `alert_chat_id`. This avoids manually copying chat IDs and prevents random Telegram users from binding themselves as the alert recipient.

### `/digest`

Requests a manual digest from the configured alert chat.

Rules:

- works only after alerts are configured
- works only from the configured alert chat
- includes new important/urgent events for the current profile digest interval
- reuses existing digest delivery for the same period instead of creating duplicates

## Digest notifications

Digest notifications are profile-level grouped summaries for `NEW` events with priority `important` or `urgent`.
Digest delivery uses Telegram as the internal notification channel. Gmail profiles can also produce digest entries, but the digest message is sent through the configured Telegram alert destination.

Supported intervals:

- every hour
- every 3 hours
- every 6 hours
- every 12 hours
- every 24 hours

Scheduled digest building is handled by Celery Beat:

```text
celery_beat -> build_and_enqueue_digest_notifications_task -> AlertDelivery(delivery_type=digest)
```

Relevant settings:

```env
DIGEST_NOTIFICATIONS_ENABLED=True
DIGEST_BEAT_MINUTE=5
DIGEST_BEAT_HOUR=*
DIGEST_MAX_EVENTS_PER_NOTIFICATION=20
```

## AI usage limits

The active AI quota model is:

- `AI_DAILY_CALL_LIMIT_PER_USER` — account-level daily AI call limit
- `AI_DAILY_COST_LIMIT_USD_PER_USER` — account-level daily estimated cost limit
- `MonitoringProfile.ai_daily_call_limit` — optional stricter per-profile limit

There is no separate global `AI_DAILY_CALL_LIMIT_PER_PROFILE` environment setting in the current configuration model. Leave the profile field empty to use only the account-level quota.

## Security notes

Current important protections include:

- encrypted storage of connected source credentials
- dedicated webhook path secret
- dedicated Telegram secret token header validation
- webhook rate limits on source and profile level
- customer anti-spam limits
- protected alert chat binding via `/start_alerts <setup-token>`
- manual digest restricted to the configured alert chat
- alert cooldown support
- idempotent alert and digest creation
- write-only admin fields for sensitive Telegram secrets
- Gmail OAuth uses the minimum read-only scope
- Gmail refresh tokens are stored only in encrypted credentials
- Gmail metadata stores only non-sensitive sync state
- failed or cancelled Gmail OAuth connections do not activate a Gmail profile

## Ops visibility

The project includes a minimal staff-only internal visibility screen for operational troubleshooting.

It tracks:

- failed alert deliveries today and total
- pending retries
- AI fallbacks and failures
- webhook rejects, including `403` and `429`
- pending/failed incoming message processing

Routes:

```text
/ops/visibility/
/ops/visibility/summary.json
```

This is not a full metrics stack. It is a pragmatic internal support screen for the MVP.

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

## Useful commands

Open Django shell:

```bash
docker compose exec web python manage.py shell
```

Show Celery worker logs:

```bash
docker compose logs -f celery_worker
```

Show Celery Beat logs:

```bash
docker compose logs -f celery_beat
```

Run Django checks:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
```

## Project status

Implemented end-to-end:

- onboarding after signup
- monitoring profile create/edit flow
- scenario presets and custom constructor
- Telegram source connection
- Telegram webhook and polling ingestion
- Telegram bot system commands with token-protected alert setup
- Telegram webhook secrets can be safely rotated with a dedicated management command, preserving the previous secret pair during a short grace period to avoid ingestion downtime in webhook mode.
- rules-first analysis and optional AI enrichment
- event creation
- instant Telegram alert delivery
- digest notifications via Celery Beat
- manual Telegram digest command
- event review / ignore / escalate / archive workflow
- minimal ops visibility
- separate Gmail monitoring profile creation flow
- Gmail OAuth connection flow
- encrypted Gmail token storage
- Gmail polling ingestion
- Gmail email parsing and normalization
- Gmail messages converted into `IncomingMessage(channel=email)`
- shared rules-first and optional AI processing for Gmail events
- Telegram alert delivery for Gmail-created events

Natural next steps:

- production deployment profile
- structured log shipping / external metrics
- richer analytics dashboard
- replay/reprocess tooling
- Gmail sync optimization with history IDs or Pub/Sub push notifications
- email-specific noise filters for newsletters/promotions/signatures
- more delivery channels such as email or webhook
- WhatsApp or additional channel adapters
- Gmail OAuth uses the minimum read-only scope
- Gmail refresh tokens are stored only in encrypted credentials
- Gmail metadata stores only non-sensitive sync state
- failed or cancelled Gmail OAuth connections do not activate a Gmail profile

## Contacts

Author: Maksym Petrykin

Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)

Telegram: [@max_p95](https://t.me/max_p95)