import logging

from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    """Custom allauth account adapter."""

    def get_email_confirmation_url(self, request, emailconfirmation):
        url = super().get_email_confirmation_url(request, emailconfirmation)

        logger.info(
            "email_confirmation_url_generated",
            extra={
                "email": emailconfirmation.email_address.email,
                "confirmation_url": url,
            },
        )

        return url

    def get_email_verification_redirect_url(self, email_address):
        """Redirect users after successful email verification."""

        return reverse("dashboard")