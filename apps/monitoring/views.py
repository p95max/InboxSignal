from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.monitoring.forms import MonitoringProfileCreateForm, MonitoringProfileUpdateForm
from apps.monitoring.models import Event, MonitoringProfile


@login_required
def dashboard_view(request):
    """Show dashboard and allow creating a monitoring profile."""

    if request.method == "POST":
        profile_form = MonitoringProfileCreateForm(request.POST)

        if profile_form.is_valid():
            profile_create_limit = check_rate_limit(
                name="registered-profile-create",
                actor=request.user.id,
                limit=settings.REGISTERED_PROFILE_CREATE_LIMIT_PER_DAY,
                period=RateLimitPeriod.DAY,
            )

            if not profile_create_limit.allowed:
                profile_form.add_error(
                    None,
                    (
                        "Profile creation limit reached. "
                        "Please try again later."
                    ),
                )
            else:
                profile = profile_form.save(owner=request.user)
                source = profile_form.connected_source

                messages.success(
                    request,
                    (
                        "Monitoring profile created. "
                        f"Telegram source #{source.id} is active."
                    ),
                )

                return redirect("profile_detail", profile_id=profile.id)
    else:
        profile_form = MonitoringProfileCreateForm()

    today_start = timezone.localtime(timezone.now()).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    user_events = Event.objects.filter(profile__owner=request.user)
    open_events = user_events.filter(status=Event.Status.NEW)

    stats = {
        "today_total": user_events.filter(created_at__gte=today_start).count(),
        "urgent_open": open_events.filter(priority=Event.Priority.URGENT).count(),
        "important_open": open_events.filter(priority=Event.Priority.IMPORTANT).count(),
        "open_total": open_events.count(),
    }

    profiles = (
        MonitoringProfile.objects.filter(owner=request.user)
        .annotate(
            events_total=Count("events", distinct=True),
            open_events_count=Count(
                "events",
                filter=Q(events__status=Event.Status.NEW),
                distinct=True,
            ),
            urgent_open_events_count=Count(
                "events",
                filter=Q(
                    events__priority=Event.Priority.URGENT,
                    events__status=Event.Status.NEW,
                ),
                distinct=True,
            ),
            important_open_events_count=Count(
                "events",
                filter=Q(
                    events__priority=Event.Priority.IMPORTANT,
                    events__status=Event.Status.NEW,
                ),
                distinct=True,
            ),
            archived_events_count=Count(
                "events",
                filter=Q(events__status=Event.Status.ARCHIVED),
                distinct=True,
            ),
            telegram_sources_count=Count(
                "connected_sources",
                filter=Q(
                    connected_sources__source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
                    connected_sources__is_deleted=False,
                ),
                distinct=True,
            ),
            active_telegram_sources_count=Count(
                "connected_sources",
                filter=Q(
                    connected_sources__source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
                    connected_sources__status=ConnectedSource.Status.ACTIVE,
                    connected_sources__is_deleted=False,
                ),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "connected_sources",
                queryset=ConnectedSource.objects.filter(
                    source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
                    is_deleted=False,
                ).order_by("name"),
                to_attr="telegram_bot_sources",
            )
        )
        .order_by("-last_event_at", "-updated_at")
    )

    return render(
        request,
        "monitoring/dashboard.html",
        {
            "stats": stats,
            "profiles": profiles,
            "profile_form": profile_form,
            "open_profile_modal": request.method == "POST" and profile_form.errors,
        },
    )

def filter_archived_events_by_decision(events, decision: str):
    """Filter archived events by the decision made before archiving."""

    if decision == "reviewed":
        return events.filter(reviewed_at__isnull=False)

    if decision == "ignored":
        return events.filter(ignored_at__isnull=False)

    if decision == "escalated":
        return events.filter(escalated_at__isnull=False)

    return events

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

    selected_priority = request.GET.get("priority", "")
    status_filter_was_provided = "status" in request.GET
    selected_status = request.GET.get("status", "")
    selected_category = request.GET.get("category", "")
    selected_archive_decision = request.GET.get("decision", "")

    valid_priorities = {choice.value for choice in Event.Priority}
    valid_statuses = {choice.value for choice in Event.Status}
    valid_categories = {choice.value for choice in Event.Category}
    valid_archive_decisions = {"reviewed", "ignored", "escalated"}

    events = (
        Event.objects.select_related(
            "incoming_message",
            "incoming_message__external_contact",
        )
        .filter(profile=profile)
        .order_by("-created_at")
    )

    if selected_priority in valid_priorities:
        events = events.filter(priority=selected_priority)
    else:
        selected_priority = ""

    if selected_status in valid_statuses:
        events = events.filter(status=selected_status)
    elif status_filter_was_provided:
        selected_status = ""
        events = events.exclude(status=Event.Status.ARCHIVED)
    else:
        selected_status = Event.Status.NEW
        events = events.filter(status=Event.Status.NEW)

    if selected_category in valid_categories:
        events = events.filter(category=selected_category)
    else:
        selected_category = ""

    if selected_status == Event.Status.ARCHIVED:
        if selected_archive_decision in valid_archive_decisions:
            events = filter_archived_events_by_decision(
                events,
                selected_archive_decision,
            )
        else:
            selected_archive_decision = ""
    else:
        selected_archive_decision = ""

    counter_events = Event.objects.filter(profile=profile)

    if selected_status in valid_statuses:
        counter_events = counter_events.filter(status=selected_status)
    elif status_filter_was_provided:
        counter_events = counter_events.exclude(status=Event.Status.ARCHIVED)
    else:
        counter_events = counter_events.filter(status=Event.Status.NEW)

    if selected_priority in valid_priorities:
        counter_events = counter_events.filter(priority=selected_priority)

    if selected_status == Event.Status.ARCHIVED:
        if selected_archive_decision in valid_archive_decisions:
            counter_events = filter_archived_events_by_decision(
                counter_events,
                selected_archive_decision,
            )

    category_counts = counter_events.aggregate(
        total=Count("id"),
        lead=Count("id", filter=Q(category=Event.Category.LEAD)),
        complaint=Count("id", filter=Q(category=Event.Category.COMPLAINT)),
        request=Count("id", filter=Q(category=Event.Category.REQUEST)),
        info=Count("id", filter=Q(category=Event.Category.INFO)),
        spam=Count("id", filter=Q(category=Event.Category.SPAM)),
    )

    def build_category_url(category: str = "") -> str:
        query_params = {}

        if selected_priority:
            query_params["priority"] = selected_priority

        if selected_status:
            query_params["status"] = selected_status
        elif status_filter_was_provided:
            query_params["status"] = ""

        if selected_archive_decision:
            query_params["decision"] = selected_archive_decision

        if category:
            query_params["category"] = category

        query_string = urlencode(query_params)
        base_url = reverse(
            "profile_detail",
            kwargs={"profile_id": profile.id},
        )

        if not query_string and not status_filter_was_provided:
            return base_url

        if not query_string and status_filter_was_provided:
            return f"{base_url}?status="

        return f"{base_url}?{query_string}"

    category_stats = [
        {
            "label": "All",
            "value": "",
            "count": category_counts["total"],
            "url": build_category_url(""),
            "is_active": selected_category == "",
            "css_class": "category-stat-all",
        },
        {
            "label": "Leads",
            "value": Event.Category.LEAD,
            "count": category_counts["lead"],
            "url": build_category_url(Event.Category.LEAD),
            "is_active": selected_category == Event.Category.LEAD,
            "css_class": "category-stat-lead",
        },
        {
            "label": "Complaints",
            "value": Event.Category.COMPLAINT,
            "count": category_counts["complaint"],
            "url": build_category_url(Event.Category.COMPLAINT),
            "is_active": selected_category == Event.Category.COMPLAINT,
            "css_class": "category-stat-complaint",
        },
        {
            "label": "Requests",
            "value": Event.Category.REQUEST,
            "count": category_counts["request"],
            "url": build_category_url(Event.Category.REQUEST),
            "is_active": selected_category == Event.Category.REQUEST,
            "css_class": "category-stat-request",
        },
        {
            "label": "Info",
            "value": Event.Category.INFO,
            "count": category_counts["info"],
            "url": build_category_url(Event.Category.INFO),
            "is_active": selected_category == Event.Category.INFO,
            "css_class": "category-stat-info",
        },
        {
            "label": "Spam",
            "value": Event.Category.SPAM,
            "count": category_counts["spam"],
            "url": build_category_url(Event.Category.SPAM),
            "is_active": selected_category == Event.Category.SPAM,
            "css_class": "category-stat-spam",
        },
    ]

    def build_filter_url(
        *,
        priority: str | None = None,
        status: str | None = None,
        category: str | None = None,
    ) -> str:
        query_params = {}

        next_priority = selected_priority if priority is None else priority
        next_status = selected_status if status is None else status
        next_category = selected_category if category is None else category

        if next_priority:
            query_params["priority"] = next_priority

        if next_status:
            query_params["status"] = next_status
        elif status == "":
            query_params["status"] = ""

        if next_category:
            query_params["category"] = next_category

        query_string = urlencode(query_params)
        base_url = reverse(
            "profile_detail",
            kwargs={"profile_id": profile.id},
        )

        if not query_string and status != "":
            return base_url

        if not query_string and status == "":
            return f"{base_url}?status="

        return f"{base_url}?{query_string}"

    priority_filter_options = [
        {
            "label": "All priorities",
            "value": "",
            "url": build_filter_url(priority=""),
            "is_active": selected_priority == "",
        },
        *[
            {
                "label": label,
                "value": value,
                "url": build_filter_url(priority=value),
                "is_active": selected_priority == value,
            }
            for value, label in Event.Priority.choices
        ],
    ]

    status_filter_options = [
        {
            "label": "All statuses",
            "value": "",
            "url": build_filter_url(status=""),
            "is_active": selected_status == "",
        },
        *[
            {
                "label": label,
                "value": value,
                "url": build_filter_url(status=value),
                "is_active": selected_status == value,
            }
            for value, label in Event.Status.choices
            if value != Event.Status.ARCHIVED
        ],
    ]

    archived_events = Event.objects.filter(
        profile=profile,
        status=Event.Status.ARCHIVED,
    )

    archive_decision_counts = archived_events.aggregate(
        total=Count("id"),
        reviewed=Count("id", filter=Q(reviewed_at__isnull=False)),
        ignored=Count("id", filter=Q(ignored_at__isnull=False)),
        escalated=Count("id", filter=Q(escalated_at__isnull=False)),
    )

    archived_events_count = archive_decision_counts["total"]

    def build_archive_decision_url(decision: str = "") -> str:
        query_params = {
            "status": Event.Status.ARCHIVED,
        }

        if selected_priority:
            query_params["priority"] = selected_priority

        if selected_category:
            query_params["category"] = selected_category

        if decision:
            query_params["decision"] = decision

        query_string = urlencode(query_params)
        base_url = reverse(
            "profile_detail",
            kwargs={"profile_id": profile.id},
        )

        return f"{base_url}?{query_string}"

    archive_decision_stats = [
        {
            "label": "All archived",
            "value": "",
            "count": archive_decision_counts["total"],
            "url": build_archive_decision_url(""),
            "is_active": selected_archive_decision == "",
            "css_class": "archive-decision-all",
        },
        {
            "label": "Reviewed",
            "value": "reviewed",
            "count": archive_decision_counts["reviewed"],
            "url": build_archive_decision_url("reviewed"),
            "is_active": selected_archive_decision == "reviewed",
            "css_class": "archive-decision-reviewed",
        },
        {
            "label": "Ignored",
            "value": "ignored",
            "count": archive_decision_counts["ignored"],
            "url": build_archive_decision_url("ignored"),
            "is_active": selected_archive_decision == "ignored",
            "css_class": "archive-decision-ignored",
        },
        {
            "label": "Escalated",
            "value": "escalated",
            "count": archive_decision_counts["escalated"],
            "url": build_archive_decision_url("escalated"),
            "is_active": selected_archive_decision == "escalated",
            "css_class": "archive-decision-escalated",
        },
    ]

    events = events[:100]

    return render(
        request,
        "monitoring/profile_detail.html",
        {
            "profile": profile,
            "events": events,
            "category_stats": category_stats,
            "archive_decision_stats": archive_decision_stats,
            "selected_priority": selected_priority,
            "selected_status": selected_status,
            "selected_category": selected_category,
            "selected_archive_decision": selected_archive_decision,
            "priority_choices": Event.Priority.choices,
            "status_choices": Event.Status.choices,
            "category_choices": Event.Category.choices,
            "priority_filter_options": priority_filter_options,
            "status_filter_options": status_filter_options,
            "archived_events_count": archived_events_count,
        },
    )


@login_required
@require_POST
def profile_delete_view(request, profile_id: int):
    """Delete a monitoring profile owned by the current user."""

    profile = (
        MonitoringProfile.objects.filter(
            id=profile_id,
            owner=request.user,
        )
        .first()
    )

    if profile is None:
        raise Http404("Monitoring profile was not found.")

    profile_name = profile.name
    profile.delete()

    messages.success(
        request,
        f'Monitoring profile "{profile_name}" was deleted.',
    )

    return redirect("dashboard")

@login_required
def profile_update_view(request, profile_id: int):
    """Update a monitoring profile owned by the current user."""

    profile = (
        MonitoringProfile.objects.filter(
            id=profile_id,
            owner=request.user,
        )
        .first()
    )

    if profile is None:
        raise Http404("Monitoring profile was not found.")

    if request.method == "POST":
        form = MonitoringProfileUpdateForm(
            request.POST,
            instance=profile,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                f'Monitoring profile "{profile.name}" was updated.',
            )

            return redirect("profile_detail", profile_id=profile.id)
    else:
        form = MonitoringProfileUpdateForm(instance=profile)

    return render(
        request,
        "monitoring/profile_update.html",
        {
            "profile": profile,
            "form": form,
        },
    )


@login_required
@require_POST
def event_action_view(request, event_id, action: str):
    """Change event status from the UI with strict owner isolation."""

    action_limit = check_rate_limit(
        name="registered-event-action",
        actor=request.user.id,
        limit=settings.REGISTERED_EVENT_ACTION_LIMIT_PER_MINUTE,
        period=RateLimitPeriod.MINUTE,
    )

    next_url = request.POST.get("next") or reverse("dashboard")

    if not action_limit.allowed:
        messages.error(
            request,
            "Too many event actions. Please try again shortly.",
        )
        return redirect(next_url)

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
    elif action == "archive":
        if event.status == Event.Status.NEW:
            raise Http404("Event must be processed before archiving.")

        event.mark_archived()
    else:
        raise Http404("Unsupported event action.")

    return redirect(next_url)