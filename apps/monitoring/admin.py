from django.contrib import admin

from apps.monitoring.models import Event, IncomingMessage, MonitoringProfile


@admin.register(MonitoringProfile)
class MonitoringProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "scenario",
        "status",
        "last_event_at",
        "created_at",
    )
    list_filter = (
        "scenario",
        "status",
        "track_leads",
        "track_complaints",
        "track_requests",
        "track_urgent",
    )
    search_fields = (
        "name",
        "owner__email",
        "business_context",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_event_at",
    )


@admin.register(IncomingMessage)
class IncomingMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "channel",
        "external_chat_id",
        "external_message_id",
        "processing_status",
        "received_at",
        "ingested_at",
    )
    list_filter = (
        "channel",
        "processing_status",
        "received_at",
    )
    search_fields = (
        "text",
        "sender_username",
        "sender_display_name",
        "external_chat_id",
        "external_message_id",
        "dedup_key",
    )
    readonly_fields = (
        "id",
        "dedup_key",
        "ingested_at",
        "processed_at",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "category",
        "priority",
        "priority_score",
        "status",
        "created_at",
    )
    list_filter = (
        "category",
        "priority",
        "status",
        "created_at",
    )
    search_fields = (
        "summary",
        "message_text_snapshot",
        "profile__name",
        "profile__owner__email",
    )
    readonly_fields = (
        "id",
        "message_text_snapshot",
        "created_at",
        "updated_at",
        "reviewed_at",
        "escalated_at",
    )