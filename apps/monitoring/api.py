from functools import wraps
from typing import Callable

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from apps.monitoring.models import Event, MonitoringProfile


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


@require_GET
@api_login_required
def profile_list_api(request: HttpRequest) -> JsonResponse:
    """Return monitoring profiles owned by the authenticated user."""

    profiles = (
        MonitoringProfile.objects.filter(owner=request.user)
        .order_by("-updated_at")
    )

    return JsonResponse(
        {
            "ok": True,
            "profiles": [
                serialize_profile(profile)
                for profile in profiles
            ],
        }
    )


@require_GET
@api_login_required
def profile_event_list_api(
    request: HttpRequest,
    profile_id: int,
) -> JsonResponse:
    """Return events for one monitoring profile owned by the authenticated user."""

    profile = (
        MonitoringProfile.objects.filter(
            id=profile_id,
            owner=request.user,
        )
        .first()
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
            "events": [
                serialize_event(event)
                for event in events
            ],
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
        "track_leads": profile.track_leads,
        "track_complaints": profile.track_complaints,
        "track_requests": profile.track_requests,
        "track_urgent": profile.track_urgent,
        "track_general_activity": profile.track_general_activity,
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