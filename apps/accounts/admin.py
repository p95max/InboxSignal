from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User

    ordering = ("email",)
    list_display = (
        "email",
        "status",
        "plan",
        "trial_ends_at",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = (
        "status",
        "plan",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    search_fields = ("email", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                )
            },
        ),
        (
            "Account status",
            {
                "fields": (
                    "status",
                    "plan",
                    "trial_ends_at",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "status",
                    "plan",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )