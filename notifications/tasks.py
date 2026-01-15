import datetime
import logging
from django.tasks import task
from django.urls import reverse
from django.utils import timezone
from notifications.emails import MorningReportEmailArgs, send_morning_report_email
from tasks.models import Task
from notifications.models import LastApplicationInteraction, WebPushSubscription
from notifications.services import send_webpush

logger = logging.getLogger(__name__)


@task()
def send_morning_report_email_task():
    """Send the morning report email to the user."""
    logger.info("Morning report email sent.")

    incomplete_tasks = (
        Task.objects.filter(status__in=["in_progress", "todo"])
        .order_by("-priority")
        .all()
    )
    incomplete_count = incomplete_tasks.count()
    incomplete_points = sum(task.completion_weight for task in incomplete_tasks)

    completed_yesterday_tasks = Task.objects.filter(
        status="completed",
        completed_at__date__exact=timezone.now().date() - datetime.timedelta(days=1),
    ).all()
    completed_yesterday_count = completed_yesterday_tasks.count()
    completed_yesterday_points = sum(
        task.completion_weight for task in completed_yesterday_tasks
    )

    args = MorningReportEmailArgs(
        incomplete_count=incomplete_count,
        incomplete_points=incomplete_points,
        yesterday_comparison="more than"
        if incomplete_count > completed_yesterday_count
        else "not more than",
        completed_yesterday_count=completed_yesterday_count,
        completed_yesterday_points=completed_yesterday_points,
        incomplete_tasks=incomplete_tasks,
    )
    send_morning_report_email(args)
    return True


@task()
def send_inactivity_notification_if_applicable_task():
    """Send inactivity notification if there hasn't been an interaction in a long time."""

    interaction = LastApplicationInteraction.objects.first()
    if interaction:
        delta = timezone.now() - interaction.last_interaction_at
        if delta >= datetime.timedelta(hours=2):
            # Send push notification about inactivity
            logger.info("Inactivity notification sent.")

            payload = {
                "title": "Catch Up",
                "body": "You have been away for a while. Check your tasks!",
                "url": "/",
            }
            subs = WebPushSubscription.objects.filter(active=True)
            sent = 0
            for sub in subs:
                try:
                    send_webpush(sub, payload)
                    sent += 1
                except Exception:
                    logger.error(
                        "Failed to send webpush to %s", sub.endpoint, exc_info=True
                    )
                    sub.active = False
                    sub.save(update_fields=["active"])

    return True


@task()
def send_long_in_progress_tasks_notification_task():
    """Send notification for tasks that have been in progress for too long."""
    threshold_date = timezone.now() - datetime.timedelta(hours=4)
    long_in_progress_tasks = Task.objects.filter(
        status="in_progress", status_last_changed_at__lt=threshold_date
    ).all()

    if long_in_progress_tasks:
        logger.info(
            f"Sending long in-progress tasks notification for {long_in_progress_tasks.count()} tasks."
        )

        for task in long_in_progress_tasks:
            logger.info(f" - {task.title} (since {task.status_last_changed_at})")

            payload = {
                "title": f"Still working on {task.title}?",
                "body": "You started this task over 4 hours ago.",
                "url": reverse("edit_task", args=[task.pk]),
            }
            subs = WebPushSubscription.objects.filter(active=True)
            sent = 0
            for sub in subs:
                try:
                    send_webpush(sub, payload)
                    sent += 1
                except Exception:
                    logger.error(
                        "Failed to send webpush to %s", sub.endpoint, exc_info=True
                    )
                    sub.active = False
                    sub.save(update_fields=["active"])

    return True
