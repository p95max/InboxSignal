from django.contrib import admin

from apps.ai.models import AIAnalysisResult


@admin.register(AIAnalysisResult)
class AIAnalysisResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "profile",
        "incoming_message",
        "event",
        "status",
        "category",
        "priority_score",
        "model_name",
        "is_latest",
        "duration_ms",
        "created_at",
    )
    list_filter = (
        "status",
        "category",
        "model_provider",
        "model_name",
        "is_latest",
        "created_at",
    )
    search_fields = (
        "summary",
        "input_text_snapshot",
        "business_context_snapshot",
        "error_message",
        "profile__name",
        "profile__owner__email",
    )
    readonly_fields = (
        "id",
        "input_text_snapshot",
        "business_context_snapshot",
        "raw_response",
        "error_message",
        "fallback_reason",
        "input_tokens",
        "output_tokens",
        "estimated_cost",
        "duration_ms",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    )