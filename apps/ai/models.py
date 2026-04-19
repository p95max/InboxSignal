import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AIAnalysisResult(models.Model):
    """Stored AI analysis result for an incoming message."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")
        FALLBACK = "fallback", _("Fallback")

    class Category(models.TextChoices):
        LEAD = "lead", _("Lead")
        COMPLAINT = "complaint", _("Complaint")
        REQUEST = "request", _("Request")
        INFO = "info", _("Info")
        SPAM = "spam", _("Spam")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    profile = models.ForeignKey(
        "monitoring.MonitoringProfile",
        on_delete=models.CASCADE,
        related_name="ai_analysis_results",
    )
    incoming_message = models.ForeignKey(
        "monitoring.IncomingMessage",
        on_delete=models.CASCADE,
        related_name="ai_analysis_results",
    )
    event = models.OneToOneField(
        "monitoring.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_analysis_result",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    model_provider = models.CharField(
        max_length=80,
        blank=True,
        help_text=_("AI provider name, for example OpenAI."),
    )
    model_name = models.CharField(
        max_length=120,
        blank=True,
        help_text=_("Model name, for example gpt-4o-mini."),
    )
    prompt_version = models.CharField(
        max_length=50,
        blank=True,
        help_text=_("Prompt version used for this analysis."),
    )

    input_text_snapshot = models.TextField(
        blank=True,
        help_text=_("Message text snapshot used for AI analysis."),
    )
    business_context_snapshot = models.TextField(
        blank=True,
        help_text=_("Business context snapshot used for AI analysis."),
    )

    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        blank=True,
    )
    priority_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )
    summary = models.CharField(max_length=500, blank=True)

    extracted_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Extracted fields returned by AI."),
    )
    raw_response = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Raw parsed AI response."),
    )

    error_message = models.TextField(blank=True)
    fallback_reason = models.TextField(blank=True)

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text=_("Estimated AI request cost."),
    )
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    is_latest = models.BooleanField(
        default=True,
        help_text=_("Marks the latest analysis result for this incoming message."),
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["profile", "status"]),
            models.Index(fields=["incoming_message", "status"]),
            models.Index(fields=["event"]),
            models.Index(fields=["model_name"]),
            models.Index(fields=["is_latest"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority_score__gte=0) & Q(priority_score__lte=100),
                name="ai_analysis_priority_score_0_100",
            ),
            models.UniqueConstraint(
                fields=["incoming_message"],
                condition=Q(is_latest=True),
                name="unique_latest_ai_analysis_per_message",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.incoming_message and not self.input_text_snapshot:
            self.input_text_snapshot = self.incoming_message.text

        if self.profile and not self.business_context_snapshot:
            self.business_context_snapshot = self.profile.business_context

        if self.is_latest and self.incoming_message_id:
            AIAnalysisResult.objects.filter(
                incoming_message_id=self.incoming_message_id,
                is_latest=True,
            ).exclude(pk=self.pk).update(is_latest=False)

        super().save(*args, **kwargs)

    def mark_started(self):
        self.status = self.Status.PENDING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    def mark_succeeded(
        self,
        *,
        category,
        priority_score,
        summary,
        extracted_data=None,
        raw_response=None,
        input_tokens=0,
        output_tokens=0,
        estimated_cost=0,
        duration_ms=None,
    ):
        self.status = self.Status.SUCCEEDED
        self.category = category
        self.priority_score = priority_score
        self.summary = summary
        self.extracted_data = extracted_data or {}
        self.raw_response = raw_response or {}
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.estimated_cost = estimated_cost
        self.duration_ms = duration_ms
        self.completed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "category",
                "priority_score",
                "summary",
                "extracted_data",
                "raw_response",
                "input_tokens",
                "output_tokens",
                "estimated_cost",
                "duration_ms",
                "completed_at",
                "updated_at",
            ]
        )

    def mark_failed(self, message):
        self.status = self.Status.FAILED
        self.error_message = str(message)[:4000]
        self.completed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )

    def mark_fallback(self, reason):
        self.status = self.Status.FALLBACK
        self.fallback_reason = str(reason)[:4000]
        self.completed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "fallback_reason",
                "completed_at",
                "updated_at",
            ]
        )

    def __str__(self):
        return f"{self.status} / {self.category or 'no-category'} / {self.priority_score}"