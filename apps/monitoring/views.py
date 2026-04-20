from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.monitoring.models import Event, MonitoringProfile


@login_required
def dashboard_view(request):
    """Show a minimal monitoring dashboard for the current user."""

    today_start = timezone.localtime(timezone.now()).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    user_events = Event.objects.filter(profile__owner=request.user)

    stats = {
        "today": user_events.filter(created_at__gte=today_start).count(),
        "urgent": user_events.filter(
            priority=Event.Priority.URGENT,
            status=Event.Status.NEW,
        ).count(),
        "important": user_events.filter(
            priority=Event.Priority.IMPORTANT,
            status=Event.Status.NEW,
        ).count(),
        "new": user_events.filter(status=Event.Status.NEW).count(),
    }

    profiles = (
        MonitoringProfile.objects.filter(owner=request.user)
        .annotate(
            events_total=Count("events", distinct=True),
            new_events_count=Count(
                "events",
                filter=Q(events__status=Event.Status.NEW),
                distinct=True,
            ),
            urgent_events_count=Count(
                "events",
                filter=Q(
                    events__priority=Event.Priority.URGENT,
                    events__status=Event.Status.NEW,
                ),
                distinct=True,
            ),
            important_events_count=Count(
                "events",
                filter=Q(
                    events__priority=Event.Priority.IMPORTANT,
                    events__status=Event.Status.NEW,
                ),
                distinct=True,
            ),
        )
        .order_by("-last_event_at", "-updated_at")
    )

    return render(
        request,
        "monitoring/dashboard.html",
        {
            "stats": stats,
            "profiles": profiles,
        },
    )


@login_required
def profile_detail_view(request, profile_id: int):
    """Show events for one monitoring profile owned by the current user."""

    profile = (
        MonitoringProfile.objects.filter(
            id=profile_id,
            owner=request.user,
        )
        .first()
    )

    if profile is None:
        raise Http404("Monitoring profile was not found.")

    events = (
        Event.objects.select_related(
            "incoming_message",
            "incoming_message__external_contact",
        )
        .filter(profile=profile)
        .order_by("-created_at")
    )

    selected_priority = request.GET.get("priority", "")
    selected_status = request.GET.get("status", "")
    selected_category = request.GET.get("category", "")

    valid_priorities = {choice.value for choice in Event.Priority}
    valid_statuses = {choice.value for choice in Event.Status}
    valid_categories = {choice.value for choice in Event.Category}

    if selected_priority in valid_priorities:
        events = events.filter(priority=selected_priority)

    if selected_status in valid_statuses:
        events = events.filter(status=selected_status)

    if selected_category in valid_categories:
        events = events.filter(category=selected_category)

    events = events[:100]

    return render(
        request,
        "monitoring/profile_detail.html",
        {
            "profile": profile,
            "events": events,
            "selected_priority": selected_priority,
            "selected_status": selected_status,
            "selected_category": selected_category,
            "priority_choices": Event.Priority.choices,
            "status_choices": Event.Status.choices,
            "category_choices": Event.Category.choices,
        },
    )


@login_required
@require_POST
def event_action_view(request, event_id, action: str):
    """Change event status from the UI with strict owner isolation."""

    event = (
        Event.objects.select_related("profile")
        .filter(
            id=event_id,
            profile__owner=request.user,
        )
        .first()
    )

    if event is None:
        raise Http404("Event was not found.")

    if action == "review":
        event.mark_reviewed()
    elif action == "ignore":
        event.mark_ignored()
    elif action == "escalate":
        event.mark_escalated()
    else:
        raise Http404("Unsupported event action.")

    next_url = request.POST.get("next") or reverse(
        "profile_detail",
        kwargs={"profile_id": event.profile_id},
    )

    return redirect(next_url)