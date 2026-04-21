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


class MonitoringProfileCreateForm(forms.ModelForm):
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
        label="Alert chat ID",
        required=False,
        max_length=255,
        help_text=(
            "Optional. Telegram chat ID or @channelusername for outgoing alerts. "
            "To get your chat ID: open your bot in Telegram, send /start, "
            "and copy the ID from the bot's reply. "
            "If empty, events will still appear in the dashboard."
        ),
    )

    class Meta:
        model = MonitoringProfile
        fields = (
            "name",
            "scenario",
            "business_context",
            "track_leads",
            "track_complaints",
            "track_requests",
            "track_urgent",
            "track_general_activity",
        )
        widgets = {
            "business_context": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 300,
                    "placeholder": "Example: We sell used cars in Germany.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in (
            "name",
            "scenario",
            "business_context",
            "telegram_bot_token",
            "alert_chat_id",
        ):
            self.fields[field_name].widget.attrs.setdefault("class", "form-control")

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

    def clean_alert_chat_id(self):
        value = self.cleaned_data.get("alert_chat_id", "").strip()

        if value and not TELEGRAM_CHAT_ID_RE.match(value):
            raise forms.ValidationError(
                "Enter a numeric Telegram chat ID or @channelusername."
            )

        return value

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
            metadata={
                "alert_chat_id": alert_chat_id,
            },
        )
        source.set_credentials(token)
        source.full_clean()
        source.save()

        self.connected_source = source

        return profile



class MonitoringProfileUpdateForm(forms.ModelForm):
    """Update editable monitoring profile settings."""

    alert_chat_id = forms.CharField(
        required=False,
        label="Alert chat ID",
        help_text=(
            "Optional. Telegram chat ID or @channelusername for alerts. "
            "Send /start to your bot to get your chat ID. "
            "If empty, alerts will not be sent."
        ),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Example: 330297984 or @channelusername",
            }
        ),
    )

    class Meta:
        model = MonitoringProfile
        fields = [
            "name",
            "scenario",
            "status",
            "business_context",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Example: Car sales monitoring",
                }
            ),
            "scenario": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "business_context": forms.Textarea(
                attrs={
                    "class": "form-control",
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

    def save(self, commit=True):
        profile = super().save(commit)

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