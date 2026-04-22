from allauth.account.views import LoginView, LogoutView, SignupView
from django.contrib import admin
from django.urls import include, path

from apps.core.views import health_check, home_view
from apps.monitoring.views import (
    dashboard_view,
    event_action_view,
    profile_delete_view,
    profile_detail_view,
)

urlpatterns = [
    path("", home_view, name="home"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("profiles/<int:profile_id>/", profile_detail_view, name="profile_detail"),
    path(
        "profiles/<int:profile_id>/delete/",
        profile_delete_view,
        name="profile_delete",
    ),
    path("events/<uuid:event_id>/<str:action>/", event_action_view, name="event_action"),

    # Backward-compatible short names used by existing templates.
    path("accounts/login/", LoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/signup/", SignupView.as_view(), name="signup"),

    # django-allauth account + social auth urls.
    path("accounts/", include("allauth.urls")),

    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),

    path("api/", include("apps.monitoring.urls")),
    path("integrations/", include("apps.integrations.urls")),
]