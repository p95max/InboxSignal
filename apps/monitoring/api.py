import json
from functools import wraps
from typing import Callable

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)
from apps.monitoring.services.scenario_presets import get_scenario_preset
from apps.monitoring.models import Event, MonitoringProfile


PROFILE_MUTABLE_FIELDS = {
    "name",
    "scenario",
    "status",
    "business_context",
    "digest_interval_hours",
    "track_leads",
    "track_complaints",
    "track_requests",
    "track_urgent",
    "track_general_activity",
    "ignore_greetings",
    "ignore_short_replies",
    "ignore_emojis",
    "urgent_negative",
    "urgent_deadlines",
    "urgent_repeated_messages",
    "extract_name",
    "extract_contact",
    "extract_budget",
    "extract_product_or_service",
    "extract_date_or_time",
    "ai_daily_call_limit",
}

PROFILE_BOOLEAN_FIELDS = {
    "track_leads",
    "track_complaints",
    "track_requests",
    "track_urgent",
    "track_general_activity",
    "ignore_greetings",
    "ignore_short_replies",
    "ignore_emojis",
    "urgent_negative",
    "urgent_deadlines",
    "urgent_repeated_messages",
    "extract_name",
    "extract_contact",
    "extract_budget",
    "extract_product_or_service",
    "extract_date_or_time",
}


def api_login_required(view_func: Callable):
    """Return JSON 401 instead of redirecting unauthenticated API users."""

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "authentication_required",
                },
                status=401,
            )

        return view_func(request, *args, **kwargs)

    return wrapper


@require_http_methods(["GET", "POST"])
@api_login_required
def profile_list_api(request: HttpRequest) -> JsonResponse:
    """List or create monitoring profiles owned by the authenticated user."""

    if request.method == "POST":
        return create_profile_api(request)

    profiles = MonitoringProfile.objects.filter(owner=request.user).order_by(
        "-updated_at"
    )

    return JsonResponse(
        {
            "ok": True,
            "profiles": [serialize_profile(profile) for profile in profiles],
        }
    )


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def profile_detail_api(
    request: HttpRequest,
    profile_id: int,
) -> JsonResponse:
    """Return, update or delete one monitoring profile owned by the user."""

    profile = get_owned_profile(
        request=request,
        profile_id=profile_id,
    )

    if profile is None:
        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
        )

    if request.method == "GET":
        return JsonResponse(
            {
                "ok": True,
                "profile": serialize_profile(profile),
            }
        )

    if request.method == "PATCH":
        return update_profile_api(
            request=request,
            profile=profile,
        )

    if request.method == "DELETE":
        profile.delete()

        return JsonResponse(
            {
                "ok": True,
                "deleted": True,
            }
        )

    return JsonResponse(
        {
            "ok": False,
            "error": "method_not_allowed",
        },
        status=405,
    )


def create_profile_api(request: HttpRequest) -> JsonResponse:
    """Create monitoring profile for authenticated user."""

    payload, error_response = parse_json_body(request)

    if error_response:
        return error_response

    cleaned_data, errors = validate_profile_payload(
        payload=payload,
        partial=False,
    )

    if errors:
        return validation_error_response(errors)

    cleaned_data = apply_scenario_preset_to_cleaned_data(
        cleaned_data=cleaned_data,
        payload=payload,
    )

    profile = MonitoringProfile(
        owner=request.user,
        **cleaned_data,
    )

    try:
        profile.full_clean()
        profile.save()
    except ValidationError as exc:
        return validation_error_response(exc.message_dict)

    return JsonResponse(
        {
            "ok": True,
            "profile": serialize_profile(profile),
        },
        status=201,
    )


def update_profile_api(
    *,
    request: HttpRequest,
    profile: MonitoringProfile,
) -> JsonResponse:
    """Update monitoring profile owned by authenticated user."""

    payload, error_response = parse_json_body(request)

    if error_response:
        return error_response

    cleaned_data, errors = validate_profile_payload(
        payload=payload,
        partial=True,
    )

    if errors:
        return validation_error_response(errors)

    cleaned_data = apply_scenario_preset_to_cleaned_data(
        cleaned_data=cleaned_data,
        payload=payload,
    )

    for field_name, value in cleaned_data.items():
        setattr(profile, field_name, value)

    try:
        profile.full_clean()
        profile.save(
            update_fields=[
                *cleaned_data.keys(),
                "updated_at",
            ]
        )
    except ValidationError as exc:
        return validation_error_response(exc.message_dict)

    profile.refresh_from_db()

    return JsonResponse(
        {
            "ok": True,
            "profile": serialize_profile(profile),
        }
    )


def get_owned_profile(
    *,
    request: HttpRequest,
    profile_id: int,
) -> MonitoringProfile | None:
    """Return profile owned by request.user or None."""

    return (
        MonitoringProfile.objects.filter(
            id=profile_id,
            owner=request.user,
        )
        .first()
    )


def parse_json_body(request: HttpRequest) -> tuple[dict, JsonResponse | None]:
    """Parse JSON request body and return payload or JSON error response."""

    if not request.body:
        return {}, None

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}, JsonResponse(
            {
                "ok": False,
                "error": "invalid_json",
            },
            status=400,
        )

    if not isinstance(payload, dict):
        return {}, JsonResponse(
            {
                "ok": False,
                "error": "invalid_payload",
                "details": {
                    "body": "JSON body must be an object.",
                },
            },
            status=400,
        )

    return payload, None


def validate_profile_payload(
    *,
    payload: dict,
    partial: bool,
) -> tuple[dict, dict]:
    """Validate profile create/update payload."""

    errors = {}
    cleaned_data = {}

    unknown_fields = sorted(set(payload) - PROFILE_MUTABLE_FIELDS)

    if unknown_fields:
        errors["unknown_fields"] = unknown_fields

    if not partial and not payload.get("name"):
        errors["name"] = "This field is required."

    for field_name, value in payload.items():
        if field_name not in PROFILE_MUTABLE_FIELDS:
            continue

        if field_name in PROFILE_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                errors[field_name] = "Expected boolean value."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "name":
            if not isinstance(value, str):
                errors[field_name] = "Expected string value."
                continue

            value = value.strip()

            if not value:
                errors[field_name] = "This field cannot be blank."
                continue

            if len(value) > 120:
                errors[field_name] = "Must be 120 characters or fewer."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "business_context":
            if not isinstance(value, str):
                errors[field_name] = "Expected string value."
                continue

            value = value.strip()

            if len(value) > 300:
                errors[field_name] = "Must be 300 characters or fewer."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "scenario":
            valid_scenarios = {choice.value for choice in MonitoringProfile.Scenario}

            if value not in valid_scenarios:
                errors[field_name] = "Unsupported scenario."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "status":
            valid_statuses = {choice.value for choice in MonitoringProfile.Status}

            if value not in valid_statuses:
                errors[field_name] = "Unsupported status."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "digest_interval_hours":
            valid_intervals = {
                choice.value
                for choice in MonitoringProfile.DigestInterval
            }

            if isinstance(value, bool) or not isinstance(value, int):
                errors[field_name] = "Expected integer value."
                continue

            if value not in valid_intervals:
                errors[field_name] = "Unsupported digest interval."
                continue

            cleaned_data[field_name] = value
            continue

        if field_name == "ai_daily_call_limit":
            if value is None or value == "":
                cleaned_data[field_name] = None
                continue

            if not isinstance(value, int):
                errors[field_name] = "Expected integer value or null."
                continue

            if value < 1:
                errors[field_name] = "Must be greater than or equal to 1."
                continue

            account_ai_limit = settings.AI_DAILY_CALL_LIMIT_PER_USER

            if value > account_ai_limit:
                errors[field_name] = (
                     "Profile AI limit cannot be higher than the account daily AI quota."
                )
                continue

            cleaned_data[field_name] = value
            continue

    return cleaned_data, errors


def validation_error_response(errors: dict) -> JsonResponse:
    """Return normalized validation error response."""

    return JsonResponse(
        {
            "ok": False,
            "error": "validation_error",
            "details": errors,
        },
        status=400,
    )


@require_GET
@api_login_required
def profile_event_list_api(
    request: HttpRequest,
    profile_id: int,
) -> JsonResponse:
    """Return events for one monitoring profile owned by the authenticated user."""

    profile = get_owned_profile(
        request=request,
        profile_id=profile_id,
    )

    if profile is None:
        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
        )

    events = (
        Event.objects.select_related(
            "incoming_message",
            "incoming_message__external_contact",
        )
        .filter(profile=profile)
        .order_by("-created_at")
    )

    status = request.GET.get("status")
    priority = request.GET.get("priority")
    category = request.GET.get("category")

    if status:
        events = events.filter(status=status)

    if priority:
        events = events.filter(priority=priority)

    if category:
        events = events.filter(category=category)

    limit = parse_positive_int(
        request.GET.get("limit"),
        default=50,
        max_value=100,
    )

    events = events[:limit]

    return JsonResponse(
        {
            "ok": True,
            "profile": serialize_profile(profile),
            "events": [serialize_event(event) for event in events],
        }
    )


@require_POST
@api_login_required
def event_review_api(
    request: HttpRequest,
    event_id,
) -> JsonResponse:
    """Mark event as reviewed."""

    return change_event_status(
        request=request,
        event_id=event_id,
        action="review",
    )


@require_POST
@api_login_required
def event_ignore_api(
    request: HttpRequest,
    event_id,
) -> JsonResponse:
    """Mark event as ignored."""

    return change_event_status(
        request=request,
        event_id=event_id,
        action="ignore",
    )


@require_POST
@api_login_required
def event_escalate_api(
    request: HttpRequest,
    event_id,
) -> JsonResponse:
    """Mark event as escalated."""

    return change_event_status(
        request=request,
        event_id=event_id,
        action="escalate",
    )


def change_event_status(
    *,
    request: HttpRequest,
    event_id,
    action: str,
) -> JsonResponse:
    """Change event status with strict owner isolation."""

    event = (
        Event.objects.select_related(
            "profile",
            "incoming_message",
            "incoming_message__external_contact",
        )
        .filter(
            id=event_id,
            profile__owner=request.user,
        )
        .first()
    )

    if event is None:
        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
        )

    if action == "review":
        event.mark_reviewed()
    elif action == "ignore":
        event.mark_ignored()
    elif action == "escalate":
        event.mark_escalated()
    else:
        return JsonResponse(
            {
                "ok": False,
                "error": "unsupported_action",
            },
            status=400,
        )

    event.refresh_from_db()

    return JsonResponse(
        {
            "ok": True,
            "event": serialize_event(event),
        }
    )


def serialize_profile(profile: MonitoringProfile) -> dict:
    """Serialize monitoring profile for API response."""

    return {
        "id": profile.id,
        "name": profile.name,
        "scenario": profile.scenario,
        "status": profile.status,
        "business_context": profile.business_context,
        "digest_interval_hours": profile.digest_interval_hours,
        "digest_interval_label": profile.get_digest_interval_hours_display(),
        "track_leads": profile.track_leads,
        "track_complaints": profile.track_complaints,
        "track_requests": profile.track_requests,
        "track_urgent": profile.track_urgent,
        "track_general_activity": profile.track_general_activity,
        "ignore_greetings": profile.ignore_greetings,
        "ignore_short_replies": profile.ignore_short_replies,
        "ignore_emojis": profile.ignore_emojis,
        "urgent_negative": profile.urgent_negative,
        "urgent_deadlines": profile.urgent_deadlines,
        "urgent_repeated_messages": profile.urgent_repeated_messages,
        "extract_name": profile.extract_name,
        "extract_contact": profile.extract_contact,
        "extract_budget": profile.extract_budget,
        "extract_product_or_service": profile.extract_product_or_service,
        "extract_date_or_time": profile.extract_date_or_time,
        "ai_daily_call_limit": profile.ai_daily_call_limit,
        "last_event_at": isoformat_or_none(profile.last_event_at),
        "created_at": isoformat_or_none(profile.created_at),
        "updated_at": isoformat_or_none(profile.updated_at),
    }


def serialize_event(event: Event) -> dict:
    """Serialize event for API response."""

    incoming_message = event.incoming_message
    contact = None
    message = None

    if incoming_message:
        message = {
            "id": str(incoming_message.id),
            "channel": incoming_message.channel,
            "external_chat_id": incoming_message.external_chat_id,
            "external_message_id": incoming_message.external_message_id,
            "sender_id": incoming_message.sender_id,
            "sender_username": incoming_message.sender_username,
            "sender_display_name": incoming_message.sender_display_name,
            "received_at": isoformat_or_none(incoming_message.received_at),
        }

        if incoming_message.external_contact:
            contact = {
                "id": incoming_message.external_contact.id,
                "external_user_id": incoming_message.external_contact.external_user_id,
                "external_chat_id": incoming_message.external_contact.external_chat_id,
                "username": incoming_message.external_contact.username,
                "display_name": incoming_message.external_contact.display_name,
                "message_count": incoming_message.external_contact.message_count,
            }

    return {
        "id": str(event.id),
        "profile_id": event.profile_id,
        "category": event.category,
        "priority": event.priority,
        "priority_score": event.priority_score,
        "status": event.status,
        "detection_source": event.detection_source,
        "title": event.title,
        "summary": event.summary,
        "message_text": event.message_text_snapshot,
        "extracted_data": event.extracted_data,
        "rule_metadata": event.rule_metadata,
        "created_at": isoformat_or_none(event.created_at),
        "updated_at": isoformat_or_none(event.updated_at),
        "reviewed_at": isoformat_or_none(event.reviewed_at),
        "ignored_at": isoformat_or_none(event.ignored_at),
        "escalated_at": isoformat_or_none(event.escalated_at),
        "incoming_message": message,
        "contact": contact,
    }


def isoformat_or_none(value):
    """Return ISO datetime string or None."""

    if value is None:
        return None

    return value.isoformat()


def parse_positive_int(
    raw_value,
    *,
    default: int,
    max_value: int,
) -> int:
    """Parse bounded positive integer from query params."""

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default

    if value <= 0:
        return default

    return min(value, max_value)



def apply_scenario_preset_to_cleaned_data(
    *,
    cleaned_data: dict,
    payload: dict,
) -> dict:
    """Apply scenario preset while preserving explicitly provided payload fields."""

    scenario = cleaned_data.get("scenario")

    if not scenario or scenario == MonitoringProfile.Scenario.CUSTOM:
        return cleaned_data

    preset = get_scenario_preset(scenario)

    for field_name, value in preset.items():
        if field_name in payload:
            continue

        cleaned_data[field_name] = value

    return cleaned_data
