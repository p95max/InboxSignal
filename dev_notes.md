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