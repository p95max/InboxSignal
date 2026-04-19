[x] accounts.User
   ↓
[x] monitoring.MonitoringProfile
   ↓
[x] integrations.ConnectedSource
   ↓
[x] monitoring.IncomingMessage
   ↓
[ ] monitoring.Event
   ↓
[ ] ai.AIAnalysisResult
   ↓
[ ] alerts.AlertDelivery

# shell
```bash
docker compose exec web python manage.py shell
```