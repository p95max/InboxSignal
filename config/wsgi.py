"""
WSGI config for config project.
"""

import os

from django.core.wsgi import get_wsgi_application

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise RuntimeError(
        "DJANGO_SETTINGS_MODULE is not set. "
        "Set it explicitly in the runtime environment."
    )

application = get_wsgi_application()