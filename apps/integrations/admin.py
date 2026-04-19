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

    class Meta:
        model = ConnectedSource
        fields = "__all__"


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
                    "webhook_secret",
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

    def save_model(self, request, obj, form, change):
        credentials = form.cleaned_data.get("credentials")

        if credentials:
            obj.set_credentials(credentials)

        super().save_model(request, obj, form, change)