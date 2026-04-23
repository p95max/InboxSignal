from django import forms
from django.contrib import admin

from apps.integrations.models import ConnectedSource


class ConnectedSourceAdminForm(forms.ModelForm):
    credentials = forms.CharField(
        required=False,
        label="Credentials",
        widget=forms.PasswordInput(render_value=False),
        help_text="Write-only field. Leave empty to keep existing credentials.",
    )
    new_webhook_secret = forms.CharField(
        required=False,
        label="Webhook secret",
        widget=forms.PasswordInput(render_value=False),
        help_text="Write-only field. Leave empty to keep existing webhook secret.",
    )
    new_webhook_secret_token = forms.CharField(
        required=False,
        label="Webhook secret token",
        widget=forms.PasswordInput(render_value=False),
        help_text="Write-only field. Leave empty to keep existing webhook secret token.",
    )

    class Meta:
        model = ConnectedSource
        exclude = (
            "webhook_secret",
            "webhook_secret_token",
        )


@admin.register(ConnectedSource)
class ConnectedSourceAdmin(admin.ModelAdmin):
    form = ConnectedSourceAdminForm

    list_display = (
        "name",
        "owner",
        "profile",
        "source_type",
        "status",
        "external_username",
        "has_credentials",
        "last_sync_at",
        "error_count",
        "created_at",
    )
    list_filter = (
        "source_type",
        "status",
        "is_deleted",
        "created_at",
    )
    search_fields = (
        "name",
        "owner__email",
        "profile__name",
        "external_id",
        "external_username",
    )
    readonly_fields = (
        "credentials_encrypted",
        "credentials_fingerprint",
        "masked_credentials",
        "masked_webhook_secret",
        "masked_webhook_secret_token",
        "last_sync_at",
        "last_error_at",
        "last_error_message",
        "error_count",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Basic info",
            {
                "fields": (
                    "owner",
                    "profile",
                    "name",
                    "source_type",
                    "status",
                    "is_deleted",
                )
            },
        ),
        (
            "External source",
            {
                "fields": (
                    "external_id",
                    "external_username",
                    "metadata",
                )
            },
        ),
        (
            "Credentials",
            {
                "fields": (
                    "credentials",
                    "masked_credentials",
                    "credentials_fingerprint",
                )
            },
        ),
        (
            "Webhook",
            {
                "fields": (
                    "new_webhook_secret",
                    "masked_webhook_secret",
                    "new_webhook_secret_token",
                    "masked_webhook_secret_token",
                )
            },
        ),
        (
            "Sync status",
            {
                "fields": (
                    "last_sync_at",
                    "last_error_at",
                    "last_error_message",
                    "error_count",
                )
            },
        ),
        (
            "System",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Stored webhook secret")
    def masked_webhook_secret(self, obj):
        if not obj.webhook_secret:
            return ""

        suffix = (
            obj.webhook_secret[-6:]
            if len(obj.webhook_secret) >= 6
            else obj.webhook_secret
        )
        return f"******{suffix}"

    @admin.display(description="Stored webhook secret token")
    def masked_webhook_secret_token(self, obj):
        if not obj.webhook_secret_token:
            return ""

        suffix = (
            obj.webhook_secret_token[-6:]
            if len(obj.webhook_secret_token) >= 6
            else obj.webhook_secret_token
        )
        return f"******{suffix}"

    def save_model(self, request, obj, form, change):
        credentials = form.cleaned_data.get("credentials")
        new_webhook_secret = form.cleaned_data.get("new_webhook_secret")
        new_webhook_secret_token = form.cleaned_data.get(
            "new_webhook_secret_token"
        )

        if credentials:
            obj.set_credentials(credentials)

        if new_webhook_secret:
            obj.webhook_secret = new_webhook_secret.strip()

        if new_webhook_secret_token:
            obj.webhook_secret_token = new_webhook_secret_token.strip()

        super().save_model(request, obj, form, change)