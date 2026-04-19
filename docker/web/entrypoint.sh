#!/bin/sh

set -e

if [ "$RUN_MIGRATIONS" = "1" ]; then
  python manage.py migrate
fi

exec "$@"