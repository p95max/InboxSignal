from decimal import Decimal
from pathlib import Path

import environ


# ==============================================================================
# Base paths
# ==============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ==============================================================================
# Environment
# ==============================================================================

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

environ.Env.read_env(BASE_DIR / ".env")


# ==============================================================================
# Core Django settings
# ==============================================================================

SECRET_KEY = env("DJANGO_SECRET_KEY")

DEBUG = env("DJANGO_DEBUG")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TIME_ZONE = "Europe/Berlin"

USE_TZ = True


# ==============================================================================
# Applications
# ==============================================================================

INSTALLED_APPS = [
    # Django apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Auth / OAuth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Project apps
    "apps.accounts.apps.AccountsConfig",
    "apps.core",
    "apps.monitoring.apps.MonitoringConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.ai.apps.AiConfig",
    "apps.alerts.apps.AlertsConfig",
]


# ==============================================================================
# Middleware
# ==============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ==============================================================================
# Templates
# ==============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.auth_settings",
            ],
        },
    }
]


# ==============================================================================
# Database
# ==============================================================================

DATABASES = {
    "default": env.db("DATABASE_URL"),
}


# ==============================================================================
# Static files
# ==============================================================================

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]


# ==============================================================================
# Authentication
# ==============================================================================

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SITE_ID = 1

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None

ACCOUNT_EMAIL_VERIFICATION = env(
    "ACCOUNT_EMAIL_VERIFICATION",
    default="mandatory",
)
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True

ACCOUNT_SIGNUP_REDIRECT_URL = "dashboard"
ACCOUNT_LOGOUT_REDIRECT_URL = "home"

ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Messaging Monitoring] "

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_EMAIL_VERIFICATION = env(
    "SOCIALACCOUNT_EMAIL_VERIFICATION",
    default="none",
)

GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET", default="")

GOOGLE_AUTH_ENABLED = bool(
    GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET
)

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "OAUTH_PKCE_ENABLED": True,
    }
}

if GOOGLE_AUTH_ENABLED:
    SOCIALACCOUNT_PROVIDERS["google"]["APP"] = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "key": "",
    }

if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS["google"]["APP"] = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "key": "",
    }


# ==============================================================================
# Redis / Cache
# ==============================================================================

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

REDIS_CACHE_URL = env("REDIS_CACHE_URL", default="redis://redis:6379/2")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_CACHE_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}


# ==============================================================================
# Celery
# ==============================================================================

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)

CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="redis://redis:6379/1",
)


# ==============================================================================
# Security / Encryption
# ==============================================================================

FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")


# ==============================================================================
# Telegram integration limits
# ==============================================================================

TELEGRAM_SOURCE_WEBHOOK_LIMIT_PER_MINUTE = env.int(
    "TELEGRAM_SOURCE_WEBHOOK_LIMIT_PER_MINUTE",
    default=120,
)

TELEGRAM_PROFILE_WEBHOOK_LIMIT_PER_DAY = env.int(
    "TELEGRAM_PROFILE_WEBHOOK_LIMIT_PER_DAY",
    default=5000,
)


# ==============================================================================
# Telegram customer anti-spam limits
# ==============================================================================

TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS = env.int(
    "TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS",
    default=15,
)

TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT = env.int(
    "TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT",
    default=10,
)

TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS = env.int(
    "TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS",
    default=60,
)


# ==============================================================================
# Telegram customer auto-replies
# ==============================================================================

TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED = env.bool(
    "TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED",
    default=True,
)

TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS = env.int(
    "TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS",
    default=300,
)


# ==============================================================================
# Registered user rate limits
# ==============================================================================

REGISTERED_PROFILE_CREATE_LIMIT_PER_DAY = env.int(
    "REGISTERED_PROFILE_CREATE_LIMIT_PER_DAY",
    default=20,
)

REGISTERED_EVENT_ACTION_LIMIT_PER_MINUTE = env.int(
    "REGISTERED_EVENT_ACTION_LIMIT_PER_MINUTE",
    default=60,
)


# ==============================================================================
# AI
# ==============================================================================

AI_ENABLED = env.bool("AI_ENABLED", default=False)

OPENAI_API_KEY = env("OPENAI_API_KEY", default="")

OPENAI_MODEL = env("OPENAI_MODEL", default="gpt-4o-mini")

AI_PROMPT_VERSION = env("AI_PROMPT_VERSION", default="ai_v1")

AI_REQUEST_TIMEOUT = env.float("AI_REQUEST_TIMEOUT", default=20.0)

AI_MIN_TEXT_LENGTH = env.int("AI_MIN_TEXT_LENGTH", default=12)

AI_DAILY_CALL_LIMIT_PER_USER = env.int(
    "AI_DAILY_CALL_LIMIT_PER_USER",
    default=50,
)

AI_DAILY_CALL_LIMIT_PER_PROFILE = env.int(
    "AI_DAILY_CALL_LIMIT_PER_PROFILE",
    default=20,
)

AI_DAILY_COST_LIMIT_USD_PER_USER = Decimal(
    env("AI_DAILY_COST_LIMIT_USD_PER_USER", default="1.00")
)

# Default values for gpt-4o-mini text tokens.
# Keep them configurable because provider pricing can change.
AI_INPUT_COST_PER_1M_TOKENS = Decimal(
    env("AI_INPUT_COST_PER_1M_TOKENS", default="0.15")
)

AI_OUTPUT_COST_PER_1M_TOKENS = Decimal(
    env("AI_OUTPUT_COST_PER_1M_TOKENS", default="0.60")
)


# ==============================================================================
# Alerts
# ==============================================================================

ALERT_COOLDOWN_URGENT_SECONDS = env.int(
    "ALERT_COOLDOWN_URGENT_SECONDS",
    default=0,
)

ALERT_COOLDOWN_IMPORTANT_SECONDS = env.int(
    "ALERT_COOLDOWN_IMPORTANT_SECONDS",
    default=0,
)


# ==============================================================================
# Logging
# ==============================================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}