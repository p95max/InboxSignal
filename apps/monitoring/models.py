import uuid

from django.conf import settings
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _


class MonitoringProfile(models.Model):
    """User-owned monitoring configuration for analyzing incoming messages."""

    class Scenario(models.TextChoices):
        LEADS = "leads", _("Lead detection")
        COMPLAINTS = "complaints", _("Complaint / negative feedback")
        BOOKING = "booking", _("Booking / request")
        URGENT = "urgent", _("Urgent messages")
        GENERAL = "general", _("General monitoring")
        CUSTOM = "custom", _("Custom")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DISABLED = "disabled", _("Disabled")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monitoring_profiles",
    )
    name = models.CharField(max_length=120)
    scenario = models.CharField(
        max_length=30,
        choices=Scenario.choices,
        default=Scenario.GENERAL,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    business_context = models.TextField(
        blank=True,
        validators=[MaxLengthValidator(300)],
        help_text=_("Optional plain text business context, max 300 characters."),
    )

    ai_daily_call_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="Leave empty to use the global AI_DAILY_CALL_LIMIT_PER_PROFILE setting.",
    )

    track_leads = models.BooleanField(default=True)
    track_complaints = models.BooleanField(default=True)
    track_requests = models.BooleanField(default=True)
    track_urgent = models.BooleanField(default=True)
    track_general_activity = models.BooleanField(default=False)

    ignore_greetings = models.BooleanField(default=True)
    ignore_short_replies = models.BooleanField(default=True)
    ignore_emojis = models.BooleanField(default=True)

    urgent_negative = models.BooleanField(default=True)
    urgent_deadlines = models.BooleanField(default=True)
    urgent_repeated_messages = models.BooleanField(default=True)

    extract_name = models.BooleanField(default=True)
    extract_contact = models.BooleanField(default=True)
    extract_budget = models.BooleanField(default=True)
    extract_product_or_service = models.BooleanField(default=True)
    extract_date_or_time = models.BooleanField(default=True)

    last_event_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["scenario"]),
            models.Index(fields=["last_event_at"]),
        ]

    def clean(self):
        """Normalize user-provided plain text fields."""
        if self.business_context:
            self.business_context = strip_tags(self.business_context).strip()

    def __str__(self):
        return f"{self.name} ({self.owner})"


class ExternalContact(models.Model):
    """External sender/contact detected from an incoming communication source."""

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("Telegram")
        WHATSAPP = "whatsapp", _("WhatsApp")
        OTHER = "other", _("Other")

    profile = models.ForeignKey(
        MonitoringProfile,
        on_delete=models.CASCADE,
        related_name="external_contacts",
    )
    source = models.ForeignKey(
        "integrations.ConnectedSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_contacts",
    )

    channel = models.CharField(
        max_length=30,
        choices=Channel.choices,
        default=Channel.TELEGRAM,
    )

    external_source_id = models.CharField(max_length=255, blank=True)
    external_chat_id = models.CharField(max_length=255, blank=True)
    external_user_id = models.CharField(max_length=255, blank=True)

    username = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)

    dedup_key = models.CharField(
        max_length=500,
        unique=True,
        editable=False,
        help_text=_("Deterministic key used to identify the same external contact."),
    )

    message_count = models.PositiveIntegerField(default=0)

    metadata = models.JSONField(default=dict, blank=True)

    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["profile", "channel"]),
            models.Index(fields=["source"]),
            models.Index(fields=["external_user_id"]),
            models.Index(fields=["external_chat_id"]),
            models.Index(fields=["username"]),
            models.Index(fields=["dedup_key"]),
            models.Index(fields=["last_seen_at"]),
        ]

    def build_dedup_key(self):
        """Build a stable key for identifying the same external contact."""
        source_part = (
            str(self.source_id)
            if self.source_id
            else self.external_source_id or "no-source"
        )
        identity_part = (
            self.external_user_id
            or self.external_chat_id
            or self.username
            or "unknown-contact"
        )

        return ":".join(
            [
                str(self.profile_id),
                self.channel,
                source_part,
                identity_part,
            ]
        )

    def save(self, *args, **kwargs):
        if not self.dedup_key:
            self.dedup_key = self.build_dedup_key()

        super().save(*args, **kwargs)

    def __str__(self):
        label = self.username or self.display_name or self.external_user_id
        return f"{label or 'unknown'} / {self.channel}"


class IncomingMessage(models.Model):
    """Raw incoming message stored before rule-based or AI processing."""

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("Telegram")
        WHATSAPP = "whatsapp", _("WhatsApp")
        OTHER = "other", _("Other")

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")
        IGNORED = "ignored", _("Ignored")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    profile = models.ForeignKey(
        MonitoringProfile,
        on_delete=models.CASCADE,
        related_name="incoming_messages",
    )
    source = models.ForeignKey(
        "integrations.ConnectedSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_messages",
    )
    external_contact = models.ForeignKey(
        ExternalContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_messages",
    )
    channel = models.CharField(
        max_length=30,
        choices=Channel.choices,
        default=Channel.TELEGRAM,
    )

    external_source_id = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("External source identifier, for example Telegram bot or chat source."),
    )
    external_chat_id = models.CharField(max_length=255, blank=True)
    external_message_id = models.CharField(max_length=255, blank=True)

    sender_id = models.CharField(max_length=255, blank=True)
    sender_username = models.CharField(max_length=255, blank=True)
    sender_display_name = models.CharField(max_length=255, blank=True)

    text = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    dedup_key = models.CharField(
        max_length=500,
        unique=True,
        editable=False,
        help_text=_("Deterministic key used to prevent duplicate message processing."),
    )

    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    processing_error = models.TextField(blank=True)

    received_at = models.DateTimeField(default=timezone.now)
    ingested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["profile", "processing_status"]),
            models.Index(fields=["source", "processing_status"]),
            models.Index(fields=["channel", "external_chat_id"]),
            models.Index(fields=["received_at"]),
            models.Index(fields=["dedup_key"]),
        ]

    def build_dedup_key(self):
        """Build a stable deduplication key from external message identifiers."""
        source_part = (
            str(self.source_id)
            if self.source_id
            else self.external_source_id or "no-source"
        )

        parts = [
            str(self.profile_id),
            self.channel,
            source_part,
            self.external_chat_id or "no-chat",
            self.external_message_id or str(self.id),
        ]

        return ":".join(parts)

    def save(self, *args, **kwargs):
        if not self.dedup_key:
            self.dedup_key = self.build_dedup_key()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.channel}:{self.external_chat_id}:{self.external_message_id}"


class Event(models.Model):
    """Structured event created from an incoming message."""

    class Category(models.TextChoices):
        LEAD = "lead", _("Lead")
        COMPLAINT = "complaint", _("Complaint")
        REQUEST = "request", _("Request")
        INFO = "info", _("Info")
        SPAM = "spam", _("Spam")

    class Priority(models.TextChoices):
        URGENT = "urgent", _("Urgent")
        IMPORTANT = "important", _("Important")
        IGNORE = "ignore", _("Ignore")

    class Status(models.TextChoices):
        NEW = "new", _("New")
        REVIEWED = "reviewed", _("Reviewed")
        IGNORED = "ignored", _("Ignored")
        ESCALATED = "escalated", _("Escalated")
        ARCHIVED = "archived", _("Archived")

    class DetectionSource(models.TextChoices):
        RULES = "rules", _("Rules")
        AI = "ai", _("AI")
        FALLBACK = "fallback", _("Fallback")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    profile = models.ForeignKey(
        MonitoringProfile,
        on_delete=models.CASCADE,
        related_name="events",
    )
    incoming_message = models.ForeignKey(
        IncomingMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.INFO,
    )
    priority = models.CharField(
        max_length=30,
        choices=Priority.choices,
        default=Priority.IGNORE,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.NEW,
    )
    detection_source = models.CharField(
        max_length=30,
        choices=DetectionSource.choices,
        default=DetectionSource.RULES,
    )

    priority_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    title = models.CharField(max_length=160, blank=True)
    summary = models.CharField(max_length=500, blank=True)

    message_text_snapshot = models.TextField(
        blank=True,
        help_text=_("Message text copied from IncomingMessage for event history stability."),
    )

    extracted_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Extracted fields like name, contact, budget, product_or_service, date_or_time."
        ),
    )
    rule_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Metadata from rule-based processing."),
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    ignored_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["profile", "status"]),
            models.Index(fields=["profile", "priority"]),
            models.Index(fields=["profile", "category"]),
            models.Index(fields=["category"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["priority_score"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority_score__gte=0) & Q(priority_score__lte=100),
                name="event_priority_score_0_100",
            ),
            models.UniqueConstraint(
                fields=["incoming_message"],
                condition=Q(incoming_message__isnull=False),
                name="unique_event_per_incoming_message",
            ),
        ]

    @classmethod
    def priority_from_score(cls, score):
        """Map numeric score to event priority."""
        if score >= 80:
            return cls.Priority.URGENT

        if score >= 50:
            return cls.Priority.IMPORTANT

        return cls.Priority.IGNORE

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if self.incoming_message and not self.message_text_snapshot:
            self.message_text_snapshot = self.incoming_message.text

        self.priority = self.priority_from_score(self.priority_score)

        update_fields = kwargs.get("update_fields")

        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.add("priority")

            if self.incoming_message and self.message_text_snapshot:
                update_fields.add("message_text_snapshot")

            kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)

        if is_new:
            MonitoringProfile.objects.filter(id=self.profile_id).update(
                last_event_at=self.created_at or timezone.now()
            )

    def mark_reviewed(self):
        self.status = self.Status.REVIEWED
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_at", "updated_at"])

    def mark_ignored(self):
        self.status = self.Status.IGNORED
        self.ignored_at = timezone.now()
        self.save(update_fields=["status", "ignored_at", "updated_at"])

    def mark_escalated(self):
        self.status = self.Status.ESCALATED
        self.escalated_at = timezone.now()
        self.save(update_fields=["status", "escalated_at", "updated_at"])

    def mark_archived(self):
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.now()
        self.save(update_fields=["status", "archived_at", "updated_at"])

    def __str__(self):
        return f"{self.category} / {self.priority} / {self.priority_score}"