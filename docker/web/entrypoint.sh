#!/bin/sh

set -e

if [ "$RUN_MIGRATIONS" = "1" ]; then
  python manage.py migrate
fi

if [ "$DJANGO_CREATE_SUPERUSER" = "True" ]; then
  python manage.py shell <<'PY'
import os

from django.contrib.auth import get_user_model


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
PY
fi

exec "$@"