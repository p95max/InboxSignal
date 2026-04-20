from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.monitoring.models import ExternalContact, MonitoringProfile


def upsert_external_contact(
    *,
    profile: MonitoringProfile,
    channel: str,
    source=None,
    external_source_id: str = "",
    external_chat_id: str = "",
    external_user_id: str = "",
    username: str = "",
    display_name: str = "",
    metadata: dict[str, Any] | None = None,
    seen_at=None,
    increment_message_count: bool = True,
) -> ExternalContact | None:
    """Create or update an external contact from incoming message sender data."""

    external_source_id = normalize_optional_value(external_source_id)
    external_chat_id = normalize_optional_value(external_chat_id)
    external_user_id = normalize_optional_value(external_user_id)
    username = normalize_optional_value(username).lstrip("@")
    display_name = normalize_optional_value(display_name)
    metadata = metadata or {}
    seen_at = seen_at or timezone.now()

    if not any([external_user_id, external_chat_id, username]):
        return None

    dedup_key = build_external_contact_dedup_key(
        profile_id=profile.id,
        channel=channel,
        source_id=source.id if source else None,
        external_source_id=external_source_id,
        external_chat_id=external_chat_id,
        external_user_id=external_user_id,
        username=username,
    )

    with transaction.atomic():
        contact, created = ExternalContact.objects.get_or_create(
            dedup_key=dedup_key,
            defaults={
                "profile": profile,
                "source": source,
                "channel": channel,
                "external_source_id": external_source_id,
                "external_chat_id": external_chat_id,
                "external_user_id": external_user_id,
                "username": username,
                "display_name": display_name,
                "metadata": metadata,
                "first_seen_at": seen_at,
                "last_seen_at": seen_at,
                "message_count": 1 if increment_message_count else 0,
            },
        )

        if created:
            return contact

        updates = {
            "last_seen_at": seen_at,
            "updated_at": timezone.now(),
        }

        if increment_message_count:
            updates["message_count"] = F("message_count") + 1

        if source and contact.source_id != source.id:
            updates["source"] = source

        if external_source_id and contact.external_source_id != external_source_id:
            updates["external_source_id"] = external_source_id

        if external_chat_id and contact.external_chat_id != external_chat_id:
            updates["external_chat_id"] = external_chat_id

        if external_user_id and contact.external_user_id != external_user_id:
            updates["external_user_id"] = external_user_id

        if username and contact.username != username:
            updates["username"] = username

        if display_name and contact.display_name != display_name:
            updates["display_name"] = display_name

        if metadata:
            merged_metadata = {
                **(contact.metadata or {}),
                **metadata,
            }
            updates["metadata"] = merged_metadata

        ExternalContact.objects.filter(pk=contact.pk).update(**updates)
        contact.refresh_from_db()

        return contact


def build_external_contact_dedup_key(
    *,
    profile_id: int,
    channel: str,
    source_id: int | None,
    external_source_id: str,
    external_chat_id: str,
    external_user_id: str,
    username: str,
) -> str:
    """Build stable external contact deduplication key."""

    source_part = str(source_id) if source_id else external_source_id or "no-source"
    identity_part = external_user_id or external_chat_id or username

    return ":".join(
        [
            str(profile_id),
            channel,
            source_part,
            identity_part,
        ]
    )


def normalize_optional_value(value) -> str:
    """Normalize optional external string value."""

    if value is None:
        return ""

    return str(value).strip()