import pytest

from apps.accounts.models import User
from apps.monitoring.models import MonitoringProfile


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