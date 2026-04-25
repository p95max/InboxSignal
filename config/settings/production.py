from .base import *  # noqa: F403,F405


DEBUG = False

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405

CSRF_TRUSTED_ORIGINS = env.list(  # noqa: F405
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=[],
)

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SESSION_COOKIE_SECURE = env.bool(  # noqa: F405
    "SESSION_COOKIE_SECURE",
    default=True,
)

CSRF_COOKIE_SECURE = env.bool(  # noqa: F405
    "CSRF_COOKIE_SECURE",
    default=True,
)

SECURE_SSL_REDIRECT = env.bool(  # noqa: F405
    "SECURE_SSL_REDIRECT",
    default=False,
)

SECURE_HSTS_SECONDS = env.int(  # noqa: F405
    "SECURE_HSTS_SECONDS",
    default=0,
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(  # noqa: F405
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)

SECURE_HSTS_PRELOAD = env.bool(  # noqa: F405
    "SECURE_HSTS_PRELOAD",
    default=False,
)

X_FRAME_OPTIONS = "DENY"