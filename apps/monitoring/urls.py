from django.urls import path

from apps.monitoring import api


app_name = "monitoring"

urlpatterns = [
    path(
        "profiles/",
        api.profile_list_api,
        name="profile_list_api",
    ),
    path(
        "profiles/<int:profile_id>/events/",
        api.profile_event_list_api,
        name="profile_event_list_api",
    ),
    path(
        "profiles/<int:profile_id>/",
        api.profile_detail_api,
        name="profile_detail_api",
    ),
    path(
        "events/<uuid:event_id>/review/",
        api.event_review_api,
        name="event_review_api",
    ),
    path(
        "events/<uuid:event_id>/ignore/",
        api.event_ignore_api,
        name="event_ignore_api",
    ),
    path(
        "events/<uuid:event_id>/escalate/",
        api.event_escalate_api,
        name="event_escalate_api",
    ),
]