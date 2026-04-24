from django.contrib import admin

from apps.monitoring.models import (
    Event,
    ExternalContact,
    IncomingMessage,
    MonitoringProfile,
)


@admin.register(MonitoringProfile)
class MonitoringProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "scenario",
        "status",
        "ai_daily_call_limit",
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

    fieldsets = (
        (
            "Basic info",
            {
                "fields": (
                    "owner",
                    "name",
                    "scenario",
                    "status",
                    "business_context",
                )
            },
        ),
        (
            "Tracking settings",
            {
                "fields": (
                    "track_leads",
                    "track_complaints",
                    "track_requests",
                    "track_urgent",
                    "track_general_activity",
                )
            },
        ),
        (
            "Ignore rules",
            {
                "fields": (
                    "ignore_greetings",
                    "ignore_short_replies",
                    "ignore_emojis",
                )
            },
        ),
        (
            "Urgency rules",
            {
                "fields": (
                    "urgent_negative",
                    "urgent_deadlines",
                    "urgent_repeated_messages",
                )
            },
        ),
        (
            "Extraction settings",
            {
                "fields": (
                    "extract_name",
                    "extract_contact",
                    "extract_budget",
                    "extract_product_or_service",
                    "extract_date_or_time",
                )
            },
        ),
        (
            "AI limits",
            {
                "fields": (
                    "ai_daily_call_limit",
                )
            },
        ),
        (
            "System",
            {
                "fields": (
                    "last_event_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(IncomingMessage)
class IncomingMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "channel",
        "external_contact",
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
        "external_contact__username",
        "external_contact__display_name",
        "external_contact__external_user_id",
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
        "detection_source",
        "created_at",
    )
    list_filter = (
        "category",
        "priority",
        "status",
        "detection_source",
        "created_at",
    )
    search_fields = (
        "title",
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
        "ignored_at",
        "escalated_at",
    )


@admin.register(ExternalContact)
class ExternalContactAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "source",
        "channel",
        "external_user_id",
        "external_chat_id",
        "username",
        "display_name",
        "message_count",
        "last_seen_at",
    )
    list_filter = (
        "channel",
        "source",
        "created_at",
        "last_seen_at",
    )
    search_fields = (
        "external_user_id",
        "external_chat_id",
        "username",
        "display_name",
        "dedup_key",
        "profile__name",
        "profile__owner__email",
    )
    readonly_fields = (
        "dedup_key",
        "message_count",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    )