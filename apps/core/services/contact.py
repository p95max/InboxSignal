from django.conf import settings
from django.core.mail import EmailMessage


def send_contact_form_email(
    *,
    name: str,
    sender_email: str,
    subject: str,
    message: str,
    client_ip: str,
    user_agent: str,
) -> int:
    """Send contact form message to project support inbox."""

    recipient_email = getattr(settings, "CONTACT_FORM_RECIPIENT_EMAIL", "")

    if not recipient_email:
        raise ValueError("CONTACT_FORM_RECIPIENT_EMAIL is not configured.")

    email_subject = f"[InboxSignal Contact] {subject}"

    email_body = "\n".join(
        [
            "New contact form message",
            "",
            f"Name: {name}",
            f"Email: {sender_email}",
            f"IP: {client_ip or '-'}",
            f"User-Agent: {user_agent or '-'}",
            "",
            "Message:",
            message,
        ]
    )

    email = EmailMessage(
        subject=email_subject,
        body=email_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
        reply_to=[sender_email],
    )

    return email.send(fail_silently=False)