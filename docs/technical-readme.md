## 1. Project summary

InboxSignal is a Django-based backend and web UI for ingesting external messages, classifying them into actionable events, and sending internal alerts.

Current MVP focus:

- **Telegram Bot API** as the primary ingestion channel
- **Django** for web UI, admin, and internal API
- **PostgreSQL** as the source of truth
- **Redis** for Celery, cache, rate limiting, cooldowns, and usage counters
- **Celery** for asynchronous processing and alert delivery
- **AI enrichment** via OpenAI for ambiguous messages

The system is not a chat client. It is a **message triage pipeline** that turns raw inbound messages into structured monitoring events.

---

## 2. Current architecture

```text
Telegram Bot API
    │
    ├─ webhook endpoint (production/public HTTPS)
    └─ polling management command (local development fallback)
            │
            ▼
ConnectedSource
            │
            ▼
IncomingMessage ingestion
            │
            ▼
Celery task: process_incoming_message_task
            │
            ├─ rules-based analysis
            ├─ optional AI analysis
            ├─ Event creation
            └─ AlertDelivery creation
                        │
                        ▼
Celery task: send_alert_delivery_task
                        │
                        ▼
Telegram alert message
```

### Runtime services

`docker-compose.yml` defines:

- `web` — Django app, migrations on startup, dev server on `:8000`
- `celery_worker` — Celery worker
- `db` — PostgreSQL 16, exposed as host port `5433`
- `redis` — Redis 7, exposed as host port `6379`

### Storage roles

- **PostgreSQL**: durable entities and history
- **Redis DB 0**: Celery broker
- **Redis DB 1**: Celery result backend
- **Redis DB 2**: cache / rate limits / cooldown markers / AI usage counters

---

## 3. Main apps and responsibilities

### `apps/accounts`

Responsibilities:

- custom `User` model with email as the login identifier
- account deletion flow
- custom allauth adapter for post-email-verification redirect

Key points:

- `User.username = None`
- email is unique and used as `USERNAME_FIELD`
- user metadata includes `status`, `plan`, `trial_ends_at`

### `apps/core`

Responsibilities:

- public pages (`home`, `about`)
- `/health/` endpoint
- shared rate-limit service
- auth-related template context flags

### `apps/integrations`

Responsibilities:

- external source model (`ConnectedSource`)
- Telegram webhook view
- Telegram polling command for local development
- Telegram webhook management command (`set/info/delete`)
- Telegram parsing, system commands, customer auto-replies, and inbound message anti-spam logic

### `apps/monitoring`

Responsibilities:

- monitoring profiles
- incoming message storage
- external contact identity tracking
- structured events
- dashboard and profile UI
- internal JSON API for profiles and events
- ingestion and processing pipeline entry points

### `apps/ai`

Responsibilities:

- AI analysis persistence (`AIAnalysisResult`)
- prompt generation
- OpenAI request client
- response parsing and normalization
- pricing and daily usage accounting

### `apps/alerts`

Responsibilities:

- alert delivery persistence (`AlertDelivery`)
- cooldown logic
- alert creation from events
- Telegram alert delivery and retry handling

---

## 4. Domain model

The core business chain is:

```text
User
  → MonitoringProfile
      → ConnectedSource
          → IncomingMessage
              → Event
                  → AlertDelivery
              → AIAnalysisResult
```

### `MonitoringProfile`

Represents one user-owned monitoring configuration.

Key fields:

- `name`
- `scenario`
- `status`
- `business_context`
- tracking toggles: leads / complaints / requests / urgent / general activity
- ignore toggles: greetings / short replies / emojis
- extraction toggles
- optional `ai_daily_call_limit`

### `ConnectedSource`

Represents an external communication source connected to a profile.

Key fields:

- `source_type`
- `status`
- `external_id`, `external_username`
- encrypted credentials via Fernet
- `webhook_secret`
- `webhook_secret_token`
- `metadata` (for example `alert_chat_id`)

Important design choice:

- credentials are stored encrypted in `credentials_encrypted`
- admin uses write-only fields for credentials and webhook secrets
- secrets are intentionally masked in admin

### `ExternalContact`

Represents a stable external sender identity per profile/source/channel.

Used for:

- contact-level history
- alert cooldown grouping
- future CRM-like expansion

### `IncomingMessage`

Represents the raw inbound message before final triage.

Key fields:

- `profile`, `source`, `external_contact`
- `channel`
- `external_chat_id`, `external_message_id`
- sender identity fields
- raw `text` and `raw_payload`
- `dedup_key`
- `processing_status`

### `Event`

Represents the actionable result of processing.

Key fields:

- `category` (`lead`, `complaint`, `request`, `info`, `spam`)
- `priority_score` (0–100)
- `priority` derived from score (`urgent`, `important`, `ignore`)
- `status` (`new`, `reviewed`, `ignored`, `escalated`, `archived`)
- `detection_source` (`rules`, `ai`, `fallback`)
- `summary`, `extracted_data`, `rule_metadata`

Important constraint:

- one `Event` per `IncomingMessage`

### `AIAnalysisResult`

Stores the full AI attempt outcome, including:

- status
- model metadata
- input/output tokens
- estimated cost
- parsed category / score / summary / extracted data
- fallback or error details

### `AlertDelivery`

Represents one notification attempt derived from an event.

Key fields:

- `channel`
- `delivery_type`
- `recipient`
- `status`
- retry metadata
- provider response payload
- idempotency key

---

## 5. End-to-end processing flow

### 5.1 Signup and profile creation

1. User signs up via django-allauth
2. User verifies email if verification is enabled
3. User opens dashboard
4. User creates a monitoring profile
5. Form creates:
   - `MonitoringProfile`
   - `ConnectedSource` of type `telegram_bot`
6. Telegram bot token is encrypted before save
7. `webhook_secret` and `webhook_secret_token` are generated

### 5.2 Telegram inbound message flow

Normal production flow:

1. Telegram sends a webhook request to:
   `/integrations/telegram/bot/<webhook_secret>/`
2. View resolves `ConnectedSource` by path secret
3. View validates `X-Telegram-Bot-Api-Secret-Token`
4. View applies source-level and profile-level webhook rate limits
5. Update payload is parsed
6. Telegram adapter normalizes the message
7. System commands are handled separately (`/start`, `/start_alerts`)
8. Customer anti-spam limits are checked
9. Message is ingested into `IncomingMessage`
10. Processing task is enqueued in Celery
11. Optional customer auto-reply is sent

### 5.3 Processing flow

1. `process_incoming_message_task` loads the message
2. Rules engine runs first
3. If message is ambiguous and AI is allowed, AI analysis runs
4. AI usage is reserved and cost recorded
5. `Event` is created if the final priority warrants it
6. `AlertDelivery` is created for important/urgent events
7. `send_alert_delivery_task` is enqueued

### 5.4 Alert flow

1. Alert task loads pending `AlertDelivery`
2. Telegram delivery text is generated
3. Message is sent through Telegram Bot API
4. Delivery is marked as:
   - `sent`
   - `failed` with retry
   - `skipped` for non-retryable conditions

---

## 6. Telegram integration details

### Supported modes

#### A. Webhook mode
Use this for real or staging environments.

Requirements:

- public HTTPS base URL
- active `ConnectedSource`
- valid bot token in encrypted credentials
- non-empty `webhook_secret`
- non-empty `webhook_secret_token`

Set webhook:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook set \
  --source-id 1 \
  --base-url https://your-public-domain.example \
  --drop-pending-updates
```

Check webhook:

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

#### B. Polling mode
Use this for local development when no public HTTPS URL exists.

Disable webhook first:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook delete \
  --source-id 1 \
  --drop-pending-updates
```

Run polling continuously:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 1
```

One-time fetch:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 1 \
  --once
```

### Supported Telegram behaviors

- normal message ingestion
- `channel_post` ingestion support at parser level
- `/start` system command
- `/start_alerts` system command with automatic alert chat binding
- customer auto-replies
- customer anti-spam throttling
- alert delivery through Telegram bot messages

### Unsupported / intentionally limited in MVP

- edited messages are ignored
- webhook security is specific to Telegram Bot API flow
- no multi-bot orchestration layer yet
- no WhatsApp adapter yet, despite domain model allowing it later

---

## 7. Security posture

## 7.1 Secrets and encrypted credentials

- Telegram bot tokens are stored encrypted with Fernet
- raw credentials are not displayed in admin
- admin only exposes write-only credential fields
- webhook secrets are masked in admin

`FIELD_ENCRYPTION_KEY` is mandatory for credential encryption/decryption.

## 7.2 Telegram webhook hardening

The project previously trusted only the secret embedded in the webhook URL path.
That was weak: if the path leaked, forged updates could be sent to the ingestion pipeline.

Current webhook trust model requires both:

1. **path-based routing secret**: `webhook_secret`
2. **Telegram secret header**: `X-Telegram-Bot-Api-Secret-Token`

Manual verification already proved the expected behavior:

- no header → `403`
- wrong header → `403`
- wrong path secret → `404`
- valid header + invalid JSON → `400`
- valid authenticated request → `200`
- repeated update is deduplicated correctly

This is the correct baseline for Telegram webhook auth in this project.

## 7.3 Rate limiting and abuse controls

### Webhook-level

- source-level limit per minute
- profile-level limit per day

### Customer-level

- minimum interval between customer messages
- daily customer message limit
- throttled customer rate-limit notice

### AI-level

- daily AI calls per user
- optional daily AI calls per profile
- daily estimated cost limit per user

### Alert-level

- alert cooldown by category/priority/contact grouping
- idempotent alert deliveries
- retry handling for transient Telegram failures

## 7.4 Current security caveats

These are not blockers for the MVP, but they should stay on the radar:

- local dev still prints email bodies to stdout when console email backend is used
- Celery worker currently runs as root in Docker dev setup
- local Redis warns about `vm.overcommit_memory`; acceptable for dev, not ideal for production
- webhook path still contains a secret, so rotation strategy matters even after header auth was added

---

## 8. AI processing design

AI is not the first line of processing.

The system uses:

```text
Rules → optional AI → final Event
```

### When AI is skipped

AI is not used when:

- AI is globally disabled
- OpenAI key is missing
- text is too short
- rules indicate empty/noise
- strong rules already produced important/urgent signal

### When AI is used

AI is used mainly for ambiguous cases where rules are weak or too generic.

### AI prompt behavior

Prompt includes:

- monitoring profile business context
- enabled signals
- message text
- deterministic JSON-only instructions

Expected AI output:

- category
- priority score
- summary
- extracted fields

### AI persistence

Every AI attempt is stored in `AIAnalysisResult`, including:

- tokens
- estimated cost
- model metadata
- parsed response
- fallback or failure state

This is the right trade-off for traceability and future auditing.

---

## 9. Alerting design

Alerts are created only for event priorities above ignore threshold.

### Default channel

Current default channel is **Telegram**.

### Recipient resolution

Recipient is resolved from `ConnectedSource.metadata["alert_chat_id"]`.

Important safeguard:

- internal alerts must not be sent back into the same incoming customer chat

### Telegram alert content

Alert text includes:

- title
- profile name
- sender/contact label
- category
- priority
- score
- analysis source
- summary
- message preview

### Retry behavior

Retryable failures:

- network/API failures that look transient

Non-retryable failures:

- chat not found
- bot blocked by user
- forbidden / no rights
- invalid peer-like Telegram errors

This split is correct and avoids retry storms on permanent failures.

---

## 10. Local development setup

## 10.1 Requirements

- Docker + Docker Compose v2
- valid `.env`
- valid `FIELD_ENCRYPTION_KEY`
- OpenAI API key if AI behavior is needed

## 10.2 Create `.env`

Start from `.env.example`.

Key settings to review first:

- `DJANGO_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_CACHE_URL`
- `FIELD_ENCRYPTION_KEY`
- `OPENAI_API_KEY`
- Telegram limits / AI limits / alert cooldowns

## 10.3 Start the stack

```bash
docker compose up --build
```

Expected behavior:

- DB initializes
- migrations are applied automatically by `web`
- superuser can be bootstrapped from env
- web server listens on `http://localhost:8000`
- Celery worker connects to Redis

## 10.4 Useful commands

### Django shell

```bash
docker compose exec web python manage.py shell
```

### Check migrations and config

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py showmigrations
```

### Create migrations

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py makemigrations accounts monitoring integrations ai alerts
```

### Apply migrations

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py migrate
```

### Celery logs

```bash
docker compose logs -f celery_worker
```

### Run all tests

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest
```

---

## 11. Internal HTTP/API surface

### Public / browser endpoints

- `/` — landing page
- `/about/` — public about page
- `/health/` — DB/Redis health check
- `/dashboard/` — authenticated dashboard
- `/profiles/<id>/` — profile detail UI
- `/profiles/<id>/edit/` — profile update UI

### Integration endpoint

- `/integrations/telegram/bot/<webhook_secret>/` — Telegram webhook endpoint

### JSON API endpoints

#### Profiles

- `GET /profiles/` — list profiles for current user
- `POST /profiles/` — create profile
- `GET /profiles/<profile_id>/` — get profile
- `PATCH /profiles/<profile_id>/` — update profile
- `DELETE /profiles/<profile_id>/` — delete profile

#### Events

- `GET /profiles/<profile_id>/events/` — list profile events with filters
- `POST /events/<event_id>/review/`
- `POST /events/<event_id>/ignore/`
- `POST /events/<event_id>/escalate/`

Authentication behavior:

- API returns JSON `401` instead of redirecting anonymous users
- owner isolation is enforced on profile/event queries

---

## 12. Testing strategy

The project already includes pytest-based coverage around the important moving parts.

Main covered areas include:

- webhook ingestion
- webhook auth hardening
- customer rate limits
- customer auto-replies
- alert delivery and retry handling
- dashboard/profile flows
- processing and AI behavior

### Recommended smoke checks after risky changes

After touching webhook/auth/integration code, manually verify:

1. missing secret token header → `403`
2. wrong secret token header → `403`
3. wrong webhook path secret → `404`
4. valid auth + invalid JSON → `400`
5. valid auth + valid message → `200`
6. repeated valid update → dedup (`created=false`)
7. downstream `Event` and `AlertDelivery` still work

That smoke set is small and high value. Keep it.

---

## 13. Observability and logging

The codebase uses structured logging across critical flow points.

Examples of logged stages:

- webhook update received
- invalid webhook auth
- ingestion started / created
- task enqueued
- AI reserved / succeeded / fallback
- event created
- alert created / sent / failed
- customer auto-reply sent
- customer rate-limited

This is enough for local troubleshooting and the next stage of operational hardening.

Recommended next improvement:

- standardize all logs on one JSON logger format across web and worker
- review which local-only logs must never ship to prod

---

## 14. Operational notes

### Admin

Django admin is already useful for inspection of:

- users
- monitoring profiles
- connected sources
- incoming messages
- external contacts
- events
- AI analysis results
- alert deliveries

Good current practice:

- secrets are masked or write-only
- encrypted credentials are never exposed as raw admin fields

### Bootstrap superuser

Controlled by env settings:

- `DJANGO_CREATE_SUPERUSER`
- `DJANGO_SUPERUSER_EMAIL`
- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`

### Local email behavior

In local development, email confirmation content may be printed to stdout depending on backend configuration.
That is acceptable for local bootstrap but must not be treated as production-safe behavior.

---

## 15. Known limitations / current debt

This is the blunt version.

- `README.md` in repo root is currently not a real project README; it looks like a change note for the webhook security fix and should be replaced.
- local development uses `runserver`, not production WSGI/ASGI setup
- Celery Beat is installed but no beat service is defined in Docker Compose
- webhook mode is secure enough for MVP now, but secret rotation is still an operational responsibility
- no production deployment doc yet in repo root
- no dedicated metrics stack yet
- no separate staging config documented
- WhatsApp/multi-channel abstraction exists mostly at model level, not at feature-complete implementation level

None of this blocks MVP development, but these are the first places that will hurt under real usage.

---

## 16. Recommended next steps

## Short term

1. Replace root `README.md` with a real project overview + setup doc
2. Add production deployment notes
3. Add secret rotation procedure for Telegram webhook credentials
4. Add a real logging section to settings docs
5. Ensure no sensitive local-only logging leaks into non-dev environments

## Medium term

1. Add Celery Beat if digest alerts are implemented
2. Add webhook signature/testing playbook to docs
3. Add metrics and structured log shipping
4. Add support for more delivery channels
5. Add backpressure/queue monitoring for Celery

## Longer term

1. Formalize adapter abstraction for multi-channel ingestion
2. Add semantic search / analytics layer
3. Add better operator tooling for replay/reprocess flows

---

## 17. Quick start checklist

If you want the shortest path from clone to working local flow:

1. Copy `.env.example` to `.env`
2. Set a valid `FIELD_ENCRYPTION_KEY`
3. Set a valid Telegram bot token via dashboard profile creation
4. Run `docker compose up --build`
5. Open `http://localhost:8000`
6. Create or use the bootstrap superuser
7. Create a monitoring profile
8. For local work, use `telegram_poll`
9. For webhook testing, use `telegram_webhook set` with public HTTPS
10. Watch `celery_worker` logs while sending messages

---

## 18. Bottom line

This project is already beyond a toy CRUD app.

It has:

- real ingestion
- async processing
- AI enrichment with usage controls
- alert delivery with retries
- Telegram integration with hardened webhook auth
- practical admin and debugging surface