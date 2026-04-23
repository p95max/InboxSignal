import re
import secrets

from cryptography.fernet import Fernet
from django import forms
from django.conf import settings
from django.db import transaction

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import MonitoringProfile


TELEGRAM_BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
TELEGRAM_CHAT_ID_RE = re.compile(r"^-?\d+$|^@[A-Za-z0-9_]{5,}$")

TRACK_FIELDS = (
    "track_leads",
    "track_complaints",
    "track_requests",
    "track_urgent",
    "track_general_activity",
)

IGNORE_FIELDS = (
    "ignore_greetings",
    "ignore_short_replies",
    "ignore_emojis",
)

URGENCY_FIELDS = (
    "urgent_negative",
    "urgent_deadlines",
    "urgent_repeated_messages",
)

EXTRACTION_FIELDS = (
    "extract_name",
    "extract_contact",
    "extract_budget",
    "extract_product_or_service",
)

PROFILE_CONSTRUCTOR_FIELDS = (
    "name",
    "scenario",
    "business_context",
    *TRACK_FIELDS,
    *IGNORE_FIELDS,
    *URGENCY_FIELDS,
    *EXTRACTION_FIELDS,
)

TEXT_LIKE_FIELDS = (
    "name",
    "scenario",
    "status",
    "business_context",
    "telegram_bot_token",
    "alert_chat_id",
    "ai_daily_call_limit",
)

FIELD_LABELS = {
    "track_leads": "Leads",
    "track_complaints": "Complaints",
    "track_requests": "Requests / bookings",
    "track_urgent": "Urgent messages",
    "track_general_activity": "General activity",
    "ignore_greetings": "Greetings",
    "ignore_short_replies": "Short replies",
    "ignore_emojis": "Emoji-only messages",
    "urgent_negative": "Negative messages",
    "urgent_deadlines": "Deadline / time-sensitive messages",
    "urgent_repeated_messages": "Repeated follow-up messages",
    "extract_name": "Name",
    "extract_contact": "Contact",
    "extract_budget": "Budget",
    "extract_product_or_service": "Product or service",
}


class MonitoringProfileConstructorMixin:
    """Shared constructor fields and UI setup for create/update forms."""

    constructor_fields = (
        *PROFILE_CONSTRUCTOR_FIELDS,
        "alert_chat_id",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._apply_widget_classes()
        self._apply_labels()
        self._apply_help_texts()

    def _apply_widget_classes(self) -> None:
        for field_name in TEXT_LIKE_FIELDS:
            field = self.fields.get(field_name)

            if field is None:
                continue

            field.widget.attrs.setdefault("class", "form-control")

    def _apply_labels(self) -> None:
        for field_name, label in FIELD_LABELS.items():
            field = self.fields.get(field_name)

            if field is not None:
                field.label = label

    def _apply_help_texts(self) -> None:
        business_context = self.fields.get("business_context")
        if business_context:
            business_context.help_text = (
                "Optional plain text business context, max 300 characters."
            )

        scenario = self.fields.get("scenario")
        if scenario:
            scenario.help_text = (
                "Choose a preset scenario or switch to Custom for manual control."
            )

        alert_chat_id = self.fields.get("alert_chat_id")
        if alert_chat_id:
            alert_chat_id.help_text = (
                "Optional. Enter Telegram chat ID for alerts, or after profile creation "
                "send `/start_alerts` to your bot from the destination chat."
            )

    def clean_business_context(self):
        value = self.cleaned_data.get("business_context", "")

        if value is None:
            return ""

        return value.strip()

    def clean_alert_chat_id(self):
        value = self.cleaned_data.get("alert_chat_id", "").strip()

        if value and not TELEGRAM_CHAT_ID_RE.match(value):
            raise forms.ValidationError(
                "Enter a numeric Telegram chat ID or @channelusername."
            )

        return value


class MonitoringProfileCreateForm(
    MonitoringProfileConstructorMixin,
    forms.ModelForm,
):
    """Create a monitoring profile and connect a Telegram bot source."""

    telegram_bot_token = forms.CharField(
        label="Telegram bot token",
        max_length=255,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={
                "autocomplete": "off",
                "placeholder": "123456789:AA...",
            },
        ),
        help_text="Token from @BotFather. It will be encrypted before saving.",
    )
    alert_chat_id = forms.CharField(
        label="Alert destination chat ID",
        required=False,
        max_length=255,
    )

    class Meta:
        model = MonitoringProfile
        fields = PROFILE_CONSTRUCTOR_FIELDS
        widgets = {
            "business_context": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 300,
                    "placeholder": "Example: We sell used cars in Germany.",
                }
            ),
            "scenario": forms.Select(),
        }

    def clean(self):
        cleaned_data = super().clean()

        try:
            Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
        except Exception as exc:
            raise forms.ValidationError(
                "FIELD_ENCRYPTION_KEY is missing or invalid. "
                "Generate a valid Fernet key before saving Telegram tokens."
            ) from exc

        return cleaned_data

    def clean_telegram_bot_token(self):
        token = self.cleaned_data["telegram_bot_token"].strip()

        if not TELEGRAM_BOT_TOKEN_RE.match(token):
            raise forms.ValidationError("Enter a valid Telegram bot token.")

        return token

    @transaction.atomic
    def save(self, *, owner):
        profile = super().save(commit=False)
        profile.owner = owner
        profile.status = MonitoringProfile.Status.ACTIVE
        profile.full_clean()
        profile.save()

        token = self.cleaned_data["telegram_bot_token"]
        alert_chat_id = self.cleaned_data.get("alert_chat_id", "")

        source = ConnectedSource(
            owner=owner,
            profile=profile,
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            name=f"{profile.name} Telegram bot",
            external_id=extract_bot_id_from_token(token),
            webhook_secret=generate_webhook_secret(),
            webhook_secret_token=generate_webhook_secret(),
            metadata={
                "alert_chat_id": alert_chat_id,
            },
        )
        source.set_credentials(token)
        source.full_clean()
        source.save()

        self.connected_source = source

        return profile


class MonitoringProfileUpdateForm(
    MonitoringProfileConstructorMixin,
    forms.ModelForm,
):
    """Update editable monitoring profile settings."""

    alert_chat_id = forms.CharField(
        required=False,
        label="Alert destination chat ID",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Example: 330297984 or @channelusername",
            }
        ),
    )

    ai_daily_call_limit = forms.IntegerField(
        required=False,
        min_value=1,
        label="AI daily call limit",
        widget=forms.NumberInput(
            attrs={
                "placeholder": "No profile AI limit",
                "min": 1,
            }
        ),
    )

    class Meta:
        model = MonitoringProfile
        fields = (
            "name",
            "scenario",
            "status",
            "business_context",
            *TRACK_FIELDS,
            *IGNORE_FIELDS,
            *URGENCY_FIELDS,
            *EXTRACTION_FIELDS,
            "ai_daily_call_limit",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Example: Car sales monitoring",
                }
            ),
            "scenario": forms.Select(),
            "status": forms.Select(),
            "business_context": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Short business context for better analysis.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        source = self.instance.connected_sources.filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            is_deleted=False,
        ).first()

        if source:
            self.fields["alert_chat_id"].initial = (
                source.metadata or {}
            ).get("alert_chat_id", "")

        account_ai_limit = settings.AI_DAILY_CALL_LIMIT_PER_USER

        self.fields["ai_daily_call_limit"].widget.attrs["max"] = account_ai_limit
        self.fields["ai_daily_call_limit"].help_text = (
            "Optional. Leave empty to disable the profile-level AI limit. "
            f"The profile will use the account-level daily AI quota "
            f"({account_ai_limit} AI calls/day). "
            "Set a number to add a stricter limit for this profile."
        )

    def clean_ai_daily_call_limit(self):
        value = self.cleaned_data.get("ai_daily_call_limit")

        if value is None:
            return None

        account_ai_limit = settings.AI_DAILY_CALL_LIMIT_PER_USER

        if value > account_ai_limit:
            raise forms.ValidationError(
                (
                    "Profile AI limit cannot be higher than the account "
                    f"daily AI quota ({account_ai_limit})."
                )
            )

        return value

    def save(self, commit=True):
        profile = super().save(commit=commit)

        alert_chat_id = self.cleaned_data.get("alert_chat_id", "").strip()

        source = profile.connected_sources.filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            is_deleted=False,
        ).first()

        if source:
            metadata = source.metadata or {}
            metadata["alert_chat_id"] = alert_chat_id

            source.metadata = metadata
            source.save(update_fields=["metadata", "updated_at"])

        return profile


def extract_bot_id_from_token(token: str) -> str:
    """Extract Telegram bot id from token prefix."""

    return token.split(":", 1)[0]


def generate_webhook_secret() -> str:
    """Generate a unique webhook secret for Telegram webhook URL."""

    while True:
        secret = secrets.token_urlsafe(32)

        if not ConnectedSource.objects.filter(webhook_secret=secret).exists():
            return secret