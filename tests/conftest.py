import pytest

from apps.accounts.models import User
from apps.monitoring.models import MonitoringProfile

from django.core.cache import cache

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
    return User.objects.create_user(
        email="test-user@example.com",
        password="testpass123",
    )


@pytest.fixture
def monitoring_profile(user):
    return MonitoringProfile.objects.create(
        owner=user,
        name="Test profile",
        business_context="Customer support for online orders.",
    )