#!/bin/sh

set -e

if [ "$RUN_MIGRATIONS" = "1" ]; then
  python manage.py migrate

  if [ "$DJANGO_CREATE_SUPERUSER" = "True" ]; then
    python manage.py shell <<'PY'
import os

from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress


email = os.getenv("DJANGO_SUPERUSER_EMAIL")
username = os.getenv("DJANGO_SUPERUSER_USERNAME")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

if not email:
    raise RuntimeError("DJANGO_SUPERUSER_EMAIL is required when DJANGO_CREATE_SUPERUSER=True")

if not password:
    raise RuntimeError("DJANGO_SUPERUSER_PASSWORD is required when DJANGO_CREATE_SUPERUSER=True")

User = get_user_model()
username_field = User.USERNAME_FIELD

lookup_value = email if username_field == "email" else username or email

user, created = User.objects.get_or_create(
    **{username_field: lookup_value},
    defaults={
        "email": email,
        "is_staff": True,
        "is_superuser": True,
        "is_active": True,
    },
)

changed = False

if hasattr(user, "email") and user.email != email:
    user.email = email
    changed = True

if not user.is_staff:
    user.is_staff = True
    changed = True

if not user.is_superuser:
    user.is_superuser = True
    changed = True

if not user.is_active:
    user.is_active = True
    changed = True

if created:
    user.set_password(password)
    user.save()
    print(f"Superuser created: {lookup_value}")
elif changed:
    user.save()
    print(f"Superuser updated: {lookup_value}")
else:
    print(f"Superuser already exists: {lookup_value}")

# Ensure allauth email verification state for admin user.
EmailAddress.objects.filter(user=user, primary=True).exclude(email=email).update(
    primary=False
)

email_address, email_created = EmailAddress.objects.get_or_create(
    user=user,
    email=email,
    defaults={
        "verified": True,
        "primary": True,
    },
)

email_changed = False

if not email_address.verified:
    email_address.verified = True
    email_changed = True

if not email_address.primary:
    email_address.primary = True
    email_changed = True

if email_changed:
    email_address.save(update_fields=["verified", "primary"])

if email_created:
    print(f"Superuser email verified: {email}")
elif email_changed:
    print(f"Superuser email verification updated: {email}")
else:
    print(f"Superuser email already verified: {email}")
PY
  fi
fi

exec "$@"