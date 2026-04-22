import pytest
from allauth.account.models import EmailAddress

from apps.accounts.models import User
from apps.monitoring.models import MonitoringProfile

from django.core.cache import cache

def create_verified_user(
    *,
    email: str = "test-user@example.com",
    password: str = "testpass123",
):
    user = User.objects.create_user(
        email=email,
        password=password,
    )

    EmailAddress.objects.create(
        user=user,
        email=email,
        verified=True,
        primary=True,
    )

    return user

@pytest.fixture(autouse=True)
def allow_testserver(settings):
    """Allow Django test client host."""

    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS.append("testserver")

@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    user = User.objects.create_user(
        email="test-user@example.com",
        password="testpass123",
    )

    EmailAddress.objects.create(
        user=user,
        email=user.email,
        verified=True,
        primary=True,
    )

    return user


@pytest.fixture
def monitoring_profile(user):
    return MonitoringProfile.objects.create(
        owner=user,
        name="Test profile",
        business_context="Test business.",
    )