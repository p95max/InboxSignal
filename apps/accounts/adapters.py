from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    """Custom allauth account adapter."""

    def get_email_verification_redirect_url(self, email_address):
        """Redirect users after successful email verification."""
        return reverse("onboarding")