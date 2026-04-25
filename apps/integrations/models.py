from cryptography.fernet import Fernet, InvalidToken

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.monitoring.models import MonitoringProfile


class ConnectedSource(models.Model):
    """External communication source connected to a monitoring profile."""

    class SourceType(models.TextChoices):
        TELEGRAM_BOT = "telegram_bot", _("Telegram bot")
        TELEGRAM_ACCOUNT = "telegram_account", _("Telegram account")
        WHATSAPP = "whatsapp", _("WhatsApp")
        WEBHOOK = "webhook", _("Webhook")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        DISABLED = "disabled", _("Disabled")
        ERROR = "error", _("Error")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connected_sources",
    )
    profile = models.ForeignKey(
        MonitoringProfile,
        on_delete=models.CASCADE,
        related_name="connected_sources",
    )

    source_type = models.CharField(
        max_length=40,
        choices=SourceType.choices,
        default=SourceType.TELEGRAM_BOT,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    name = models.CharField(
        max_length=120,
        help_text=_("User-friendly source name, for example Telegram sales bot."),
    )

    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("External source id, for example bot id, account id or webhook id."),
    )
    external_username = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("External username, for example Telegram bot username."),
    )

    credentials_encrypted = models.TextField(
        blank=True,
        help_text=_("Encrypted credentials. Never display this value in admin."),
    )
    credentials_fingerprint = models.CharField(
        max_length=16,
        blank=True,
        help_text=_("Short non-sensitive fingerprint for identifying configured credentials."),
    )

    webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Optional secret for validating incoming webhook requests."),
    )
    webhook_secret_token = models.CharField(
        max_length=255,
        blank=True,
        help_text=_(
            "Telegram webhook secret token used in "
            "X-Telegram-Bot-Api-Secret-Token header."
        ),
    )

    previous_webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text=_("Previous webhook path secret accepted during rotation grace period."),
    )

    previous_webhook_secret_token = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Previous Telegram webhook secret token accepted during rotation grace period."),
    )

    previous_webhook_secret_valid_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Until when previous webhook credentials are accepted."),
    )

    webhook_secret_rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Last webhook secret rotation timestamp."),
    )

    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)

    error_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["profile", "status"]),
            models.Index(fields=["source_type"]),
            models.Index(fields=["external_id"]),
            models.Index(fields=["is_deleted"]),
            models.Index(fields=["webhook_secret"]),
            models.Index(fields=["previous_webhook_secret"]),
            models.Index(fields=["previous_webhook_secret_valid_until"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "source_type", "external_id"],
                condition=models.Q(is_deleted=False) & ~models.Q(external_id=""),
                name="unique_active_source_per_profile_type_external_id",
            ),
            models.UniqueConstraint(
                fields=["webhook_secret"],
                condition=(
                        models.Q(is_deleted=False)
                        & models.Q(source_type="telegram_bot")
                        & ~models.Q(webhook_secret="")
                ),
                name="unique_active_telegram_webhook_secret",
            ),
            models.UniqueConstraint(
                fields=["previous_webhook_secret"],
                condition=(
                        models.Q(is_deleted=False)
                        & models.Q(source_type="telegram_bot")
                        & ~models.Q(previous_webhook_secret="")
                ),
                name="unique_active_previous_telegram_webhook_secret",
            ),
        ]

    def __str__(self):
        return f"{self.name} / {self.source_type} / {self.status}"

    @staticmethod
    def _get_fernet():
        key = settings.FIELD_ENCRYPTION_KEY

        if not key:
            raise ValueError("FIELD_ENCRYPTION_KEY is not configured.")

        return Fernet(key.encode())

    def set_credentials(self, raw_value):
        """Encrypt and store source credentials."""
        if not raw_value:
            self.credentials_encrypted = ""
            self.credentials_fingerprint = ""
            return

        raw_value = raw_value.strip()
        fernet = self._get_fernet()

        self.credentials_encrypted = fernet.encrypt(raw_value.encode()).decode()
        self.credentials_fingerprint = raw_value[-6:]

    def get_credentials(self):
        """Decrypt source credentials."""
        if not self.credentials_encrypted:
            return ""

        fernet = self._get_fernet()

        try:
            return fernet.decrypt(self.credentials_encrypted.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Could not decrypt source credentials.") from exc

    def clear_credentials(self):
        self.credentials_encrypted = ""
        self.credentials_fingerprint = ""

    def mark_active(self):
        self.status = self.Status.ACTIVE
        self.last_error_message = ""
        self.save(update_fields=["status", "last_error_message", "updated_at"])

    def mark_disabled(self):
        self.status = self.Status.DISABLED
        self.save(update_fields=["status", "updated_at"])

    def mark_sync_success(self):
        self.status = self.Status.ACTIVE
        self.last_sync_at = timezone.now()
        self.last_error_message = ""
        self.save(
            update_fields=[
                "status",
                "last_sync_at",
                "last_error_message",
                "updated_at",
            ]
        )

    def mark_sync_error(self, message):
        self.status = self.Status.ERROR
        self.last_error_at = timezone.now()
        self.last_error_message = str(message)[:2000]
        self.error_count += 1
        self.save(
            update_fields=[
                "status",
                "last_error_at",
                "last_error_message",
                "error_count",
                "updated_at",
            ]
        )

    @property
    def has_credentials(self):
        return bool(self.credentials_encrypted)

    @property
    def masked_credentials(self):
        if not self.credentials_fingerprint:
            return ""

        return f"******{self.credentials_fingerprint}"

    def has_valid_previous_webhook_secret(self, now=None) -> bool:
        """Return True if previous webhook credentials are still within grace window."""

        if not self.previous_webhook_secret:
            return False

        if not self.previous_webhook_secret_token:
            return False

        if self.previous_webhook_secret_valid_until is None:
            return False

        now = now or timezone.now()

        return self.previous_webhook_secret_valid_until > now

    def clear_previous_webhook_secret(self, *, save=True) -> None:
        """Remove expired previous webhook credentials."""

        self.previous_webhook_secret = ""
        self.previous_webhook_secret_token = ""
        self.previous_webhook_secret_valid_until = None

        if save:
            self.save(
                update_fields=[
                    "previous_webhook_secret",
                    "previous_webhook_secret_token",
                    "previous_webhook_secret_valid_until",
                    "updated_at",
                ]
            )