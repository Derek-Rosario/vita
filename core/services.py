import json
import os
from typing import Literal
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.http import HttpResponse

from core.views import HttpRequest


def add_htmx_trigger(
    response: HttpResponse,
    trigger_name: str,
    trigger_data: dict = {},
):
    """Add or edit HX-Trigger header to include custom trigger data."""
    existing_triggers = {}
    if response.has_header("HX-Trigger"):
        existing_triggers = json.loads(response["HX-Trigger"])
    existing_triggers[trigger_name] = trigger_data
    response["HX-Trigger"] = json.dumps(existing_triggers)


def add_toast(
    response: HttpResponse,
    type: Literal["success"] | Literal["error"] | Literal["info"],
    message: str,
):
    """Add a toast message to an HttpResponse using HTMX triggers. Optionally add a custom voice message."""
    add_htmx_trigger(
        response,
        "toastMessage",
        {"type": type, "message": message},
    )


def add_voice_message(
    response: HttpResponse,
    message: str,
):
    add_htmx_trigger(response, "speak", {"message": message})


def send_email(to_address, subject, body):
    from django.core.mail import send_mail
    from django.conf import settings

    with get_connection(
        host=settings.RESEND_SMTP_HOST,
        port=settings.RESEND_SMTP_PORT,
        username=settings.RESEND_SMTP_USERNAME,
        password=os.environ["RESEND_API_KEY"],
        use_tls=True,
    ) as connection:
        r = EmailMessage(
            subject=subject,
            body=body,
            to=[to_address],
            from_email=settings.DEFAULT_FROM_EMAIL,
            connection=connection,
        ).send()
