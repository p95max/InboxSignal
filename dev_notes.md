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
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py shell


# celery logs
docker compose logs -f celery_worker

# pytest
## all tests
docker compose run --rm -e RUN_MIGRATIONS=0 web pytest
