import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AlertDelivery(models.Model):
    """Delivery record for an alert notification created from a monitoring event."""

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("Telegram")
        EMAIL = "email", _("Email")
        WEBHOOK = "webhook", _("Webhook")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    class DeliveryType(models.TextChoices):
        INSTANT = "instant", _("Instant")
        DIGEST = "digest", _("Digest")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    profile = models.ForeignKey(
        "monitoring.MonitoringProfile",
        on_delete=models.CASCADE,
        related_name="alert_deliveries",
    )
    event = models.ForeignKey(
        "monitoring.Event",
        on_delete=models.CASCADE,
        related_name="alert_deliveries",
    )

    channel = models.CharField(
        max_length=30,
        choices=Channel.choices,
        default=Channel.TELEGRAM,
    )
    delivery_type = models.CharField(
        max_length=30,
        choices=DeliveryType.choices,
        default=DeliveryType.INSTANT,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    recipient = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Target recipient, for example Telegram chat id, email or webhook alias."),
    )

    idempotency_key = models.CharField(
        max_length=500,
        unique=True,
        editable=False,
        help_text=_("Deterministic key used to prevent duplicate alert deliveries."),
    )

    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Notification payload prepared for delivery."),
    )
    response_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Provider response payload after delivery attempt."),
    )

    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("External provider message id after successful delivery."),
    )

    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)

    error_message = models.TextField(blank=True)

    scheduled_at = models.DateTimeField(default=timezone.now)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["profile", "status"]),
            models.Index(fields=["event", "status"]),
            models.Index(fields=["channel", "status"]),
            models.Index(fields=["delivery_type"]),
            models.Index(fields=["scheduled_at"]),
            models.Index(fields=["next_retry_at"]),
            models.Index(fields=["idempotency_key"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="alert_delivery_max_attempts_gte_1",
            ),
        ]

    def build_idempotency_key(self):
        """Build a stable idempotency key to avoid duplicate notifications."""
        parts = [
            str(self.profile_id),
            str(self.event_id),
            self.channel,
            self.delivery_type,
            self.recipient or "no-recipient",
        ]

        return ":".join(parts)

    def save(self, *args, **kwargs):
        if not self.idempotency_key:
            self.idempotency_key = self.build_idempotency_key()

        super().save(*args, **kwargs)

    def mark_sent(self, provider_message_id="", response_payload=None):
        self.status = self.Status.SENT
        self.attempts += 1
        self.provider_message_id = provider_message_id or self.provider_message_id
        self.response_payload = response_payload or {}
        self.error_message = ""
        self.sent_at = timezone.now()
        self.next_retry_at = None

        self.save(
            update_fields=[
                "status",
                "attempts",
                "provider_message_id",
                "response_payload",
                "error_message",
                "sent_at",
                "next_retry_at",
                "updated_at",
            ]
        )

    def mark_failed(self, message, next_retry_at=None):
        self.attempts += 1
        self.error_message = str(message)[:4000]

        if next_retry_at and self.attempts < self.max_attempts:
            self.status = self.Status.PENDING
            self.next_retry_at = next_retry_at
        else:
            self.status = self.Status.FAILED
            self.failed_at = timezone.now()
            self.next_retry_at = None

        self.save(
            update_fields=[
                "status",
                "attempts",
                "error_message",
                "failed_at",
                "next_retry_at",
                "updated_at",
            ]
        )

    def mark_skipped(self, reason=""):
        self.status = self.Status.SKIPPED
        self.error_message = str(reason)[:4000]
        self.skipped_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "error_message",
                "skipped_at",
                "updated_at",
            ]
        )

    @property
    def can_retry(self):
        return self.status in {self.Status.PENDING, self.Status.FAILED} and (
            self.attempts < self.max_attempts
        )

    def __str__(self):
        return f"{self.channel} / {self.delivery_type} / {self.status}"