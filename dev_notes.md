[x] accounts.User
   ↓
[x] monitoring.MonitoringProfile
   ↓
[x] integrations.ConnectedSource
   ↓
[x] monitoring.IncomingMessage
   ↓
[x] monitoring.Event
   ↓
[x] ai.AIAnalysisResult
   ↓
[x] alerts.AlertDelivery

# shell
```bash
docker compose exec web python manage.py shell
```

# make migrations in docker env
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py makemigrations accounts monitoring integrations ai alerts
```
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py migrate
```
## check migrations
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py check
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py showmigrations
```

# shell
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py shell
```

# celery logs
```bash
docker compose logs -f celery_worker
```

# pytest
## all tests
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest
```
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook set \
  --source-id 1 \
  --base-url https://identify-symbols-often-suggested.trycloudflare.com     \
  --drop-pending-updates
```
# Telegram polling for local development

Webhook requires public HTTPS URL. For local development use polling.

## Disable webhook before polling

```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_webhook delete \
  --source-id 2 \
  --drop-pending-updates
```  
# Start polling
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 2
```

# One-time polling check
```bash
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py telegram_poll \
  --source-id 2 \
  --once
```