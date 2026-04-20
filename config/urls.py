from django.contrib import admin
from django.urls import path, include

from apps.core.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    
    path("api/", include("apps.monitoring.urls")),

    path("integrations/", include("apps.integrations.urls")),
]