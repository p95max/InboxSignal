from django.contrib import admin

from apps.alerts.models import AlertDelivery


@admin.register(AlertDelivery)
class AlertDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "event",
        "channel",
        "delivery_type",
        "status",
        "recipient",
        "attempts",
        "max_attempts",
        "scheduled_at",
        "sent_at",
        "created_at",
    )
    list_filter = (
        "channel",
        "delivery_type",
        "status",
        "scheduled_at",
        "sent_at",
        "created_at",
    )
    search_fields = (
        "recipient",
        "provider_message_id",
        "error_message",
        "profile__name",
        "profile__owner__email",
        "event__summary",
        "event__message_text_snapshot",
        "idempotency_key",
    )
    readonly_fields = (
        "id",
        "idempotency_key",
        "payload",
        "response_payload",
        "provider_message_id",
        "attempts",
        "error_message",
        "scheduled_at",
        "next_retry_at",
        "sent_at",
        "failed_at",
        "skipped_at",
        "created_at",
        "updated_at",
    )