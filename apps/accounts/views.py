from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST


@login_required
@require_POST
def account_delete_view(request):
    """Delete current user account after explicit email confirmation."""

    confirmation_email = request.POST.get("confirmation_email", "").strip()
    expected_email = request.user.email

    if confirmation_email != expected_email:
        messages.error(
            request,
            "Account deletion was not confirmed. Enter your email address exactly.",
        )
        return redirect(request.POST.get("next") or "dashboard")

    user = request.user

    logout(request)
    user.delete()

    messages.success(
        request,
        "Your account and related monitoring data were deleted.",
    )

    return redirect("home")