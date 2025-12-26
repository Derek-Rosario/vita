import os
from dataclasses import dataclass
from django.core.mail import get_connection, EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from mjml import mjml_to_html
from django.utils.html import strip_tags

from tasks.models import Task


def send_mail(to_address, subject, body_html):
    with get_connection(
        host=settings.RESEND_SMTP_HOST,
        port=settings.RESEND_SMTP_PORT,
        username=settings.RESEND_SMTP_USERNAME,
        password=os.environ["RESEND_API_KEY"],
        use_tls=True,
    ) as connection:
        body_text = strip_tags(body_html)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_address],
            connection=connection,
        )

        msg.attach_alternative(body_html, "text/html")
        return msg.send()


@dataclass
class MorningReportEmailArgs:
    in_progress_count: int
    in_progress_points: int
    yesterday_comparison: str
    completed_yesterday_count: int
    completed_yesterday_points: int
    in_progress_tasks: BaseManager[Task]


def send_morning_report_email(args: MorningReportEmailArgs):
    subject = "Your Morning Report"
    to_email = settings.SELF_EMAIL

    raw_mjml = render_to_string(
        "notifications/emails/morning_report.html",
        context=args.__dict__,
    )

    result = mjml_to_html(raw_mjml)

    return send_mail(
        to_address=to_email,
        subject=subject,
        body_html=result.html,
    )
