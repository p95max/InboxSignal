[x] accounts.User
   ↓
[x] monitoring.MonitoringProfile
   ↓
[ ] integrations.ConnectedSource
   ↓
[ ] monitoring.IncomingMessage
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