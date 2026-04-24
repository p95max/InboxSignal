# Messaging Monitoring System — Technical README

## 1. Project summary

InboxSignal is a Django-based backend and web UI for ingesting external messages, classifying them into actionable events, and sending internal alerts and digests.

Current MVP focus:

- **Telegram Bot API** as the primary ingestion channel
- **Django** for web UI, admin, onboarding, profile configuration, and internal API
- **PostgreSQL** as the source of truth
- **Redis** for Celery, cache, rate limiting, cooldowns, locks, and usage counters
- **Celery Worker** for asynchronous processing and alert delivery
- **Celery Beat** for scheduled digest notification building
- **AI enrichment** via OpenAI for ambiguous messages
- **Ops visibility** for minimal staff-only operational troubleshooting

The system is not a chat client. It is a **message triage pipeline** that turns raw inbound messages into structured monitoring events.

---

## 2. Current architecture

```text
Telegram Bot API
    │
    ├─ webhook endpoint                 production / public HTTPS
    └─ polling management command        local development fallback
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
            └─ instant AlertDelivery creation
                        │
                        ▼
Celery task: send_alert_delivery_task
                        │
                        ▼
Telegram alert chat
```

Scheduled digest flow:

```text
Celery Beat
    │
    ▼
build_and_enqueue_digest_notifications_task
    │
    ├─ find active Telegram sources with digest enabled
    ├─ check whether profile digest interval is due
    ├─ aggregate NEW important/urgent events for completed period
    ├─ create AlertDelivery(delivery_type=digest) idempotently
    └─ enqueue send_alert_delivery_task
            │
            ▼
Telegram digest message
```

### Runtime services

`docker-compose.yml` defines:

- `web` — Django app, migrations on startup, development server on `:8000`
- `celery_worker` — Celery worker for processing, alerts, and digest delivery
- `celery_beat` — Celery Beat scheduler for digest builder task
- `db` — PostgreSQL 16, exposed as host port `5433`
- `redis` — Redis 7, exposed as host port `6379`

### Storage roles

- **PostgreSQL**: durable entities and history
- **Redis DB 0**: Celery broker
- **Redis DB 1**: Celery result backend
- **Redis DB 2**: cache / rate limits / cooldown markers / locks / AI usage counters / ops counters

---

## 3. Main apps and responsibilities

### `apps/accounts`

Responsibilities:

- custom `User` model with email as login identifier
- account deletion flow
- custom allauth adapter for post-email-verification redirect to onboarding

Key points:

- `User.username = None`
- email is unique and used as `USERNAME_FIELD`
- user metadata includes `status`, `plan`, `trial_ends_at`

### `apps/core`

Responsibilities:

- public pages (`home`, `about`)
- `/health/` endpoint
- shared Redis-backed rate-limit service
- auth-related template context flags
- lightweight ops metrics counters for webhook rejects

### `apps/integrations`

Responsibilities:

- external source model (`ConnectedSource`)
- Telegram webhook view
- Telegram polling command for local development
- Telegram webhook management command (`set`, `info`, `delete`)
- Telegram parsing and normalization
- Telegram system commands:
  - `/start`
  - `/start_alerts <setup-token>`
  - `/digest`
- customer auto-replies
- customer-level inbound anti-spam logic

### `apps/monitoring`

Responsibilities:

- monitoring profiles
- onboarding flow
- profile create/edit constructor
- scenario presets
- incoming message storage
- external contact identity tracking
- structured events
- dashboard and profile detail UI
- internal JSON API for profiles and events
- staff-only ops visibility view
- ingestion and processing pipeline entry points

### `apps/ai`

Responsibilities:

- AI analysis persistence (`AIAnalysisResult`)
- prompt generation
- OpenAI request client
- response parsing and normalization
- extraction filtering based on profile settings
- pricing and daily usage accounting
- account-level and optional profile-level AI usage limits

### `apps/alerts`

Responsibilities:

- alert delivery persistence (`AlertDelivery`)
- instant alert delivery creation
- digest alert delivery creation
- cooldown logic
- idempotency for instant and digest notifications
- Telegram alert and digest delivery
- retry handling for transient Telegram failures

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
- `digest_enabled`
- `digest_interval_hours`
- `ai_daily_call_limit`
- tracking toggles:
  - `track_leads`
  - `track_complaints`
  - `track_requests`
  - `track_urgent`
  - `track_general_activity`
- ignore toggles:
  - `ignore_greetings`
  - `ignore_short_replies`
  - `ignore_emojis`
- urgency toggles:
  - `urgent_negative`
  - `urgent_deadlines`
  - `urgent_repeated_messages`
- extraction toggles:
  - `extract_name`
  - `extract_contact`
  - `extract_budget`
  - `extract_product_or_service`
  - `extract_date_or_time`
- `last_event_at`

Digest intervals:

- `1` — every hour
- `3` — every 3 hours
- `6` — every 6 hours
- `12` — every 12 hours
- `24` — every 24 hours

Important design choices:

- `business_context` is limited to 300 characters
- `business_context` is stripped from HTML in `clean()`
- `ai_daily_call_limit` is optional; empty means only account-level AI quota applies
- scenario presets do not override explicitly changed form fields
- `custom` scenario does not apply preset defaults

### `ConnectedSource`

Represents an external communication source connected to a profile.

Key fields:

- `owner`
- `profile`
- `source_type`
- `status`
- `external_id`
- `external_username`
- `credentials_encrypted`
- `credentials_fingerprint`
- `webhook_secret`
- `webhook_secret_token`
- `metadata`
- `last_sync_at`, `last_error_at`, `last_error_message`, `error_count`
- `is_deleted`

Current Telegram-specific metadata:

```json
{
  "alert_chat_id": "...",
  "alert_setup_token": "..."
}
```

Important design choices:

- credentials are encrypted with Fernet
- raw credentials are never displayed in admin
- admin uses write-only fields for credentials and webhook secrets
- webhook path secret and Telegram secret token are separate values
- when `alert_chat_id` is empty, a setup token is generated for `/start_alerts`

### `ExternalContact`

Represents a stable external sender identity per profile/source/channel.

Used for:

- contact-level history
- alert cooldown grouping
- future CRM-like expansion

### `IncomingMessage`

Represents the raw inbound message before final triage.

Key fields:

- `profile`
- `source`
- `external_contact`
- `channel`
- `external_source_id`
- `external_chat_id`
- `external_message_id`
- sender identity fields
- `text`
- `raw_payload`
- `dedup_key`
- `processing_status`
- timestamps

### `Event`

Represents the actionable result of processing.

Key fields:

- `category`: `lead`, `complaint`, `request`, `info`, `spam`
- `priority_score`: `0..100`
- `priority`: `urgent`, `important`, `ignore`
- `status`: `new`, `reviewed`, `ignored`, `escalated`, `archived`
- `detection_source`: `rules`, `ai`, `fallback`
- `summary`
- `extracted_data`
- `rule_metadata`

Important constraint:

- one `Event` per `IncomingMessage`

### `AIAnalysisResult`

Stores the full AI attempt outcome, including:

- status
- model metadata
- prompt version
- input/output tokens
- estimated cost
- parsed category / score / summary / extracted data
- fallback or error details
- latest-result marker per incoming message

### `AlertDelivery`

Represents one notification attempt derived from an event.

Key fields:

- `profile`
- `event`
- `channel`
- `delivery_type`: `instant` or `digest`
- `status`: `pending`, `sent`, `failed`, `skipped`
- `recipient`
- `idempotency_key`
- `payload`
- `response_payload`
- retry metadata
- provider message id
- timestamps

Important design choices:

- `idempotency_key` is unique
- `delivery_type` separates instant alert delivery from digest delivery
- digest delivery uses a representative event but stores the full digest data in payload

---

## 5. Product and user flow

### 5.1 Signup and onboarding

1. User signs up via django-allauth.
2. User verifies email if verification is enabled.
3. User is redirected to onboarding.
4. Onboarding creates the first monitoring profile and Telegram bot source.
5. User lands on dashboard with profile status, alert setup state, digest state, open events, and AI usage.

### 5.2 Additional profile creation

After onboarding, authenticated users can create additional monitoring profiles from the dashboard.

The create form creates:

- `MonitoringProfile`
- `ConnectedSource` of type `telegram_bot`

Telegram bot token is encrypted before save.

### 5.3 Profile editing

The edit form updates monitoring behavior without replacing connected Telegram source credentials.

Editable areas:

- name
- scenario
- status
- business context
- digest enabled/frequency
- tracking toggles
- ignore toggles
- urgency toggles
- extraction toggles
- optional profile AI limit
- alert destination chat ID

### 5.4 Scenario presets

Available scenarios:

| Scenario | Purpose |
|---|---|
| `leads` | detect potential buyers and sales intent |
| `complaints` | detect complaints and negative feedback |
| `booking` | detect booking/service requests |
| `urgent` | detect time-sensitive or risky messages |
| `general` | broad monitoring with general activity enabled |
| `custom` | no preset; user controls all fields manually |

Preset behavior:

- presets set `track_*`, `ignore_*`, `urgent_*`, and `extract_*` fields
- explicit user changes in submitted form are preserved
- `custom` skips preset application

---

## 6. Telegram integration details

### 6.1 Webhook mode

Use webhook mode for staging/production when a public HTTPS URL exists.

Requirements:

- active `ConnectedSource`
- valid encrypted Telegram bot token
- non-empty `webhook_secret`
- non-empty `webhook_secret_token`
- public HTTPS base URL

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

### 6.2 Polling mode

Use polling for local development when no public HTTPS URL exists.

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

### 6.3 Supported Telegram update types

Supported:

- normal bot messages
- channel posts at parser level
- text and caption normalization

Intentionally limited in MVP:

- edited messages are ignored
- no multi-bot orchestration layer yet
- no WhatsApp adapter yet, despite model-level preparation

---

## 7. Telegram system commands

System commands bypass customer ingestion, customer anti-spam checks, customer auto-replies, and event processing.

### `/start`

Returns a basic service response:

- confirms that the bot is active
- lists `/start_alerts` and `/digest`

### `/start_alerts <setup-token>`

Binds the current Telegram chat as the internal alert destination.

Rules:

- if this chat is already configured, the bot returns a positive no-op message
- if another chat is already configured, the bot rejects the binding
- if setup token is missing in source metadata, the bot asks user to regenerate the setup command from dashboard
- if provided token is invalid, the bot rejects the binding
- if token is valid, `metadata.alert_chat_id` is saved and `metadata.alert_setup_token` is removed

This is the correct MVP-level protection: possession of the bot link is not enough to hijack alert delivery.

### `/digest`

Builds and sends a manual digest for the configured alert chat.

Rules:

- rejected when alerts are not configured
- rejected from any chat except configured `alert_chat_id`
- rejected when profile digest is disabled
- uses the profile digest interval as the manual period length
- returns a no-events message when no new important/urgent events exist
- creates and enqueues digest delivery when a new digest exists
- returns an already-exists message when the period digest was already created

---

## 8. Webhook security and abuse controls

### 8.1 Webhook trust model

Telegram webhook requests must pass two checks:

1. path secret: `/integrations/telegram/bot/<webhook_secret>/`
2. header secret: `X-Telegram-Bot-Api-Secret-Token`

Expected behavior:

- wrong path secret → `404`
- missing/wrong secret token header → `403`
- valid auth + invalid JSON → `400`
- valid auth + valid message → `200`
- repeated valid update → deduplication handles it idempotently

### 8.2 Webhook-level rate limits

- source-level limit per minute
- profile-level limit per day

Rejected requests increment lightweight ops counters.

### 8.3 Customer-level anti-spam

Customer messages are guarded by:

- minimum interval between accepted customer messages
- daily customer message limit
- throttled rate-limit notice

Duplicate Telegram deliveries are allowed through to normal deduplication, so provider retries do not get incorrectly treated as spam.

### 8.4 Alert-level protections

- instant alert idempotency
- digest idempotency
- alert cooldown by profile/category/priority/contact
- non-retryable Telegram failures are skipped instead of retried forever

---

## 9. End-to-end message processing flow

Normal inbound flow:

1. Telegram sends webhook request or polling command fetches update.
2. Source is resolved by `webhook_secret` or `source_id`.
3. Webhook mode validates Telegram secret token header.
4. Webhook rate limits are applied.
5. Telegram update is parsed into normalized message data.
6. System commands are handled separately.
7. Customer anti-spam limits are checked.
8. Message is ingested into `IncomingMessage` with deduplication key.
9. Processing task is enqueued.
10. Customer auto-reply is sent for newly created customer messages.
11. Celery worker runs rules-first processing.
12. AI is used only when rules are not confident enough and AI is allowed.
13. Event is created when final result warrants it.
14. Instant alert delivery is created for important/urgent events.
15. Alert delivery task sends Telegram message.

---

## 10. Rules and AI processing design

The processing model is:

```text
Rules → optional AI → final Event
```

### 10.1 When AI is skipped

AI is skipped when:

- AI is globally disabled
- OpenAI key is missing
- text is too short
- rules indicate empty/noise
- strong rules already produced important/urgent signal

### 10.2 When AI is used

AI is mainly used for ambiguous messages where rules are weak or too generic.

### 10.3 AI prompt behavior

Prompt includes:

- monitoring profile business context
- enabled signals from profile tracking toggles
- message text
- deterministic JSON-only instructions

Expected AI output:

- category
- priority score
- summary
- extracted fields

### 10.4 Extraction filtering

AI may return extracted values, but the system filters extracted data based on profile extraction toggles.

This keeps the constructor meaningful: disabling `extract_budget` or `extract_contact` affects actual stored event payloads, not only the UI.

### 10.5 AI persistence

Every AI attempt is stored in `AIAnalysisResult`, including:

- tokens
- estimated cost
- model metadata
- parsed response
- fallback or failure state

This is necessary for traceability, debugging, and future auditability.

### 10.6 AI usage limits

The current configuration model is intentionally simple:

- `AI_DAILY_CALL_LIMIT_PER_USER`
- `AI_DAILY_COST_LIMIT_USD_PER_USER`
- optional `MonitoringProfile.ai_daily_call_limit`

If profile limit is empty, the system applies only account-level call and cost limits.

There is no active global `AI_DAILY_CALL_LIMIT_PER_PROFILE` setting. Do not document or reintroduce it unless the implementation changes.

---

## 11. Alerting design

Alerts are created only for events above ignore threshold.

### 11.1 Instant alerts

Instant alerts are created for important/urgent events.

Recipient is resolved from:

```python
ConnectedSource.metadata["alert_chat_id"]
```

Important safeguard:

- internal alerts must not be sent back into the same incoming customer chat

### 11.2 Alert content

Telegram instant alert includes:

- title
- profile name
- sender/contact label
- category
- priority
- priority score
- analysis source
- summary
- message preview
- dashboard link

### 11.3 Retry behavior

Retryable failures:

- network/API failures that look transient

Non-retryable failures:

- chat not found
- bot blocked by user
- forbidden / no rights
- peer-like Telegram permission errors

Non-retryable failures are marked as skipped. This avoids retry storms on permanent configuration errors.

---

## 12. Digest notification design

Digest notifications are grouped Telegram summaries of events that are still actionable.

### 12.1 Included events

Digest includes events matching:

- same `MonitoringProfile`
- `status = new`
- `priority in [important, urgent]`
- `created_at >= period.start`
- `created_at < period.end`

Digest output is ordered by:

1. priority score descending
2. created time descending

Only up to `DIGEST_MAX_EVENTS_PER_NOTIFICATION` events are included.

### 12.2 Period model

Digest periods are half-open intervals:

```text
[start, end)
```

Scheduled digest uses the last completed period for the configured profile interval.

Examples:

- hourly digest built at `14:05` covers `13:00 <= event < 14:00`
- 3-hour digest built at `15:05` covers `12:00 <= event < 15:00`
- 24-hour digest built at `00:05` covers previous local day

### 12.3 Due check

A profile digest is due when the completed hour is divisible by the profile interval:

```text
period_end.hour % digest_interval_hours == 0
```

Supported intervals are deliberately constrained to `1`, `3`, `6`, `12`, and `24` hours.

### 12.4 Idempotency

Digest idempotency key includes:

- delivery type marker
- channel
- profile id
- source id
- recipient
- period start
- period end

This prevents duplicate digest deliveries when Celery Beat runs twice, worker retries, or manual triggering collides with an existing period.

### 12.5 Builder lock

The scheduled digest builder also uses a short Redis lock per completed hour.

This lock is a concurrency guard. The database-level idempotency key remains the durable duplicate protection.

### 12.6 Manual digest

Manual `/digest` uses a period ending at current local time and looking back by the profile interval.

It is useful for local testing and operational review, but it is still protected by alert chat binding.

---

## 13. Ops visibility

The project includes a minimal staff-only operational visibility screen.

Routes:

```text
GET /ops/visibility/
GET /ops/visibility/summary.json
```

Tracked cards:

- failed alert deliveries today
- failed alert deliveries total
- pending retries
- AI fallbacks today
- AI failures today
- webhook rejects today
- webhook `403` rejects today
- webhook `429` rejects today
- pending incoming messages
- failed incoming messages

Webhook reject counters are stored as lightweight Redis daily counters with a 3-day TTL.

This is not a replacement for Prometheus/Sentry/log shipping. It is a pragmatic internal dashboard for MVP support and demo stability.

---

## 14. Local development setup

### 14.1 Requirements

- Docker
- Docker Compose v2
- valid `.env`
- valid Fernet `FIELD_ENCRYPTION_KEY`
- OpenAI API key if AI behavior is needed
- Telegram bot token if Telegram integration is tested end-to-end

### 14.2 Create `.env`

Start from `.env.example`.

Key settings to review first:

- `DJANGO_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_CACHE_URL`
- `FIELD_ENCRYPTION_KEY`
- `OPENAI_API_KEY`
- Telegram limits
- AI limits
- digest settings
- alert cooldowns

### 14.3 Start stack

```bash
docker compose up --build
```

Expected behavior:

- database initializes
- migrations are applied automatically by `web`
- superuser can be bootstrapped from env
- web server listens on `http://localhost:8000`
- Celery worker connects to Redis
- Celery Beat schedules digest builder task when digest notifications are enabled

---

## 15. Environment settings

### 15.1 Digest settings

```env
DIGEST_NOTIFICATIONS_ENABLED=True
DIGEST_BEAT_MINUTE=5
DIGEST_BEAT_HOUR=*
DIGEST_MAX_EVENTS_PER_NOTIFICATION=20
```

Notes:

- `DIGEST_NOTIFICATIONS_ENABLED=False` disables scheduled digest creation
- profile-level `digest_enabled=False` disables digest for that profile
- `DIGEST_BEAT_MINUTE` and `DIGEST_BEAT_HOUR` configure scheduler timing
- digest period is still determined by each profile's `digest_interval_hours`

### 15.2 AI settings

```env
AI_ENABLED=True
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
AI_PROMPT_VERSION=ai_v1
AI_REQUEST_TIMEOUT=20
AI_MIN_TEXT_LENGTH=12
AI_DAILY_CALL_LIMIT_PER_USER=50
AI_DAILY_COST_LIMIT_USD_PER_USER=0.05
AI_INPUT_COST_PER_1M_TOKENS=0.15
AI_OUTPUT_COST_PER_1M_TOKENS=0.60
```

Profile-specific AI limit is stored in the database field:

```text
MonitoringProfile.ai_daily_call_limit
```

### 15.3 Telegram limits

```env
TELEGRAM_SOURCE_WEBHOOK_LIMIT_PER_MINUTE=120
TELEGRAM_PROFILE_WEBHOOK_LIMIT_PER_DAY=5000
TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS=120
TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT=15
TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS=60
TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED=True
TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS=300
```

### 15.4 Registered user limits

```env
REGISTERED_PROFILE_CREATE_LIMIT_PER_DAY=20
REGISTERED_EVENT_ACTION_LIMIT_PER_MINUTE=60
```

### 15.5 Alert cooldowns

```env
ALERT_COOLDOWN_URGENT_SECONDS=0
ALERT_COOLDOWN_IMPORTANT_SECONDS=0
```

Default `0` means cooldown is disabled.

---

## 16. Useful commands

### Django shell

```bash
docker compose exec web python manage.py shell
```

### Check migrations and config

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
```

```bash
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

### Celery worker logs

```bash
docker compose logs -f celery_worker
```

### Celery Beat logs

```bash
docker compose logs -f celery_beat
```

### Run tests

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest
```

Focused examples:

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/integrations/test_telegram_webhook.py -q
```

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/alerts -q
```

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest tests/monitoring/test_ops_visibility.py -q
```

---

## 17. Internal HTTP/API surface

### Public / browser endpoints

- `/` — landing page
- `/about/` — public about page
- `/health/` — DB/Redis health check
- `/dashboard/` — authenticated dashboard
- `/onboarding/` — first profile setup after signup
- `/profiles/new/` — create additional profile
- `/profiles/<id>/` — profile detail UI
- `/profiles/<id>/edit/` — profile update UI
- `/ops/visibility/` — staff-only ops visibility page

### Integration endpoint

- `/integrations/telegram/bot/<webhook_secret>/` — Telegram webhook endpoint

### Ops JSON endpoint

- `/ops/visibility/summary.json` — staff-only ops snapshot

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
- ops visibility requires staff access

---

## 18. Testing strategy

The pytest suite covers the main risk areas:

- onboarding profile/source creation
- profile create/update constructor behavior
- scenario presets
- webhook ingestion
- webhook auth hardening
- customer rate limits
- customer auto-replies
- Telegram system commands
- alert delivery and retry handling
- digest period boundaries
- digest idempotency / repeated runs
- manual digest command behavior
- dashboard/profile flows
- processing and AI behavior
- ops visibility access and counters

### Recommended smoke checks after integration changes

After touching webhook/auth/Telegram code, manually verify:

1. wrong webhook path secret → `404`
2. missing secret token header → `403`
3. wrong secret token header → `403`
4. valid auth + invalid JSON → `400`
5. valid auth + valid message → `200`
6. repeated valid update → dedup (`created=false`)
7. `/start` does not create an incoming message
8. `/start_alerts <wrong-token>` does not bind alert chat
9. `/start_alerts <valid-token>` binds alert chat once
10. `/digest` works only from configured alert chat
11. downstream `Event` and `AlertDelivery` still work

---

## 19. Observability and logging

The codebase uses structured logging across critical flow points.

Examples of logged stages:

- webhook update received
- invalid webhook auth
- webhook rate limited
- system command handled
- customer message rate limited
- ingestion started / created
- task enqueued
- AI reserved / succeeded / fallback
- event created
- alert created / sent / failed / skipped
- digest built / reused / skipped
- customer auto-reply sent

Current visibility layers:

- structured logs
- `/health/`
- Django admin
- staff-only ops visibility page
- Redis daily ops counters for webhook rejects

Recommended production hardening:

- standardize JSON logger format across web, worker, and beat
- add external error tracking
- add metric shipping
- add Celery queue depth monitoring
- add alerting for repeated digest/alert failures

---

## 20. Operational notes

### Admin

Django admin is useful for inspecting:

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

That is acceptable for local bootstrap, but it must not be treated as production-safe behavior.

---

## 21. Known limitations / current debt

This is the blunt version.

- local development uses Django `runserver`, not production WSGI/ASGI setup
- no production deployment document yet
- no dedicated metrics stack yet
- no external error tracking yet
- no separate staging config documented
- webhook secret rotation procedure should be documented before real production use
- digest delivery currently targets Telegram only
- WhatsApp/multi-channel abstraction exists mostly at model level, not as a feature-complete adapter
- ops visibility is useful but intentionally minimal; it is not an observability platform

None of this blocks MVP development, but these are the first places that will hurt under real usage.

---

## 22. Recommended next steps

### Short term

1. Add production deployment notes.
2. Document Telegram webhook secret rotation.
3. Add a short operator playbook for digest/alert failures.
4. Add `.env.example` entries for every documented optional setting, including `DIGEST_MAX_EVENTS_PER_NOTIFICATION` if missing.
5. Review sensitive local-only logs before any non-dev deployment.

### Medium term

1. Add structured log shipping.
2. Add external error tracking.
3. Add queue depth / failed task monitoring.
4. Add replay/reprocess tooling for failed incoming messages.
5. Add richer analytics around categories, priorities, and response patterns.

### Longer term

1. Formalize adapter abstraction for multi-channel ingestion.
2. Add more delivery channels: email, webhook, Slack-like target.
3. Add semantic search / analytics layer.
4. Add CRM export or lightweight follow-up workflow.

---

## 23. Quick start checklist

Shortest local path from clone to working Telegram flow:

1. Copy `.env.example` to `.env`.
2. Set a valid `FIELD_ENCRYPTION_KEY`.
3. Set database and Redis variables.
4. Run `docker compose up --build`.
5. Open `http://localhost:8000`.
6. Create or use bootstrap superuser.
7. Complete onboarding.
8. Create a monitoring profile and provide Telegram bot token.
9. Send `/start_alerts <setup-token>` from the intended alert chat.
10. For local work, use `telegram_poll`.
11. For webhook testing, use `telegram_webhook set` with public HTTPS.
12. Watch `celery_worker` and `celery_beat` logs while sending messages.
13. Trigger `/digest` from the alert chat to verify digest delivery.

---

## 24. Bottom line

This project is already beyond a toy CRUD app.

It has:

- real Telegram ingestion
- onboarding and configurable product flow
- scenario presets and custom constructor
- async processing
- AI enrichment with usage controls
- event triage lifecycle
- instant alerts with retries
- digest notifications with Celery Beat and idempotency
- Telegram system commands with protected alert setup
- hardened webhook auth
- practical admin and ops visibility surface