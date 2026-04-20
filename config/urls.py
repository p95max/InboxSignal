from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views import health_check
from apps.monitoring.views import (
    dashboard_view,
    event_action_view,
    profile_detail_view,
)

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard", permanent=False), name="home"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("profiles/<int:profile_id>/", profile_detail_view, name="profile_detail"),
    path("events/<uuid:event_id>/<str:action>/", event_action_view, name="event_action"),

    path("accounts/", include("django.contrib.auth.urls")),

    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),

    path("api/", include("apps.monitoring.urls")),
    path("integrations/", include("apps.integrations.urls")),
]