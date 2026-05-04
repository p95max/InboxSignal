from types import SimpleNamespace

import pytest
from django.urls import reverse


pytestmark = pytest.mark.django_db


def build_contact_payload(**overrides):
    payload = {
        "name": "Max Tester",
        "email": "max@example.com",
        "subject": "Support request",
        "message": "Hello, I need help with my monitoring setup.",
        "website": "",
    }
    payload.update(overrides)

    return payload


def enable_test_email_backend(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "noreply@example.com"
    settings.CONTACT_FORM_RECIPIENT_EMAIL = "support@example.com"


def test_contact_page_is_public(client, settings):
    settings.TURNSTILE_ENABLED = False
    settings.TURNSTILE_SITE_KEY = ""

    response = client.get(reverse("contact"))

    assert response.status_code == 200
    assert b"Contact us" in response.content
    assert b"Send message" in response.content
    assert b"cf-turnstile" not in response.content


def test_contact_page_renders_turnstile_widget_when_enabled(client, settings):
    settings.TURNSTILE_ENABLED = True
    settings.TURNSTILE_SITE_KEY = "test-site-key"

    response = client.get(reverse("contact"))

    content = response.content.decode()

    assert response.status_code == 200
    assert "cf-turnstile" in content
    assert 'data-sitekey="test-site-key"' in content
    assert 'id="contact-submit-button"' in content
    assert "disabled" in content


def test_contact_form_sends_email_when_turnstile_is_disabled(
    client,
    settings,
    mailoutbox,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = False
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 5

    response = client.post(
        reverse("contact"),
        data=build_contact_payload(),
    )

    assert response.status_code == 302
    assert response.url == reverse("contact")

    assert len(mailoutbox) == 1

    email = mailoutbox[0]

    assert email.to == ["support@example.com"]
    assert email.reply_to == ["max@example.com"]
    assert email.from_email == "noreply@example.com"
    assert email.subject == "[InboxSignal Contact] Support request"
    assert "Max Tester" in email.body
    assert "max@example.com" in email.body
    assert "Hello, I need help with my monitoring setup." in email.body


def test_contact_form_verifies_turnstile_before_sending_email(
    client,
    settings,
    mailoutbox,
    mocker,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = True
    settings.TURNSTILE_SITE_KEY = "test-site-key"
    settings.TURNSTILE_SECRET_KEY = "test-secret-key"
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 5

    verify_mock = mocker.patch(
        "apps.core.views.verify_turnstile_token",
        return_value=SimpleNamespace(
            success=True,
            error_codes=(),
        ),
    )

    response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            **{
                "cf-turnstile-response": "valid-turnstile-token",
            }
        ),
    )

    assert response.status_code == 302
    assert response.url == reverse("contact")

    verify_mock.assert_called_once_with(
        token="valid-turnstile-token",
        remote_ip="127.0.0.1",
    )

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["support@example.com"]


def test_contact_form_does_not_send_email_when_turnstile_fails(
    client,
    settings,
    mailoutbox,
    mocker,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = True
    settings.TURNSTILE_SITE_KEY = "test-site-key"
    settings.TURNSTILE_SECRET_KEY = "test-secret-key"
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 5

    verify_mock = mocker.patch(
        "apps.core.views.verify_turnstile_token",
        return_value=SimpleNamespace(
            success=False,
            error_codes=("invalid-input-response",),
        ),
    )

    response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            **{
                "cf-turnstile-response": "bad-turnstile-token",
            }
        ),
    )

    assert response.status_code == 200
    assert len(mailoutbox) == 0

    verify_mock.assert_called_once_with(
        token="bad-turnstile-token",
        remote_ip="127.0.0.1",
    )

    assert (
        b"Security check failed. Please refresh the page and try again."
        in response.content
    )


def test_contact_form_does_not_send_email_when_honeypot_is_filled(
    client,
    settings,
    mailoutbox,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = False
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 5

    response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            website="https://spam.example.com",
        ),
    )

    assert response.status_code == 200
    assert len(mailoutbox) == 0

    form = response.context["form"]

    assert "website" in form.errors
    assert "Invalid form submission." in form.errors["website"]


def test_contact_form_rate_limit_blocks_repeated_submissions(
    client,
    settings,
    mailoutbox,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = False
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 1

    first_response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            subject="First request",
        ),
    )

    second_response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            subject="Second request",
        ),
    )

    assert first_response.status_code == 302
    assert second_response.status_code == 200

    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == "[InboxSignal Contact] First request"


def test_contact_form_rejects_invalid_email(
    client,
    settings,
    mailoutbox,
):
    enable_test_email_backend(settings)
    settings.TURNSTILE_ENABLED = False
    settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR = 5

    response = client.post(
        reverse("contact"),
        data=build_contact_payload(
            email="not-an-email",
        ),
    )

    assert response.status_code == 200
    assert len(mailoutbox) == 0

    form = response.context["form"]

    assert "email" in form.errors