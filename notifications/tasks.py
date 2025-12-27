import datetime
import logging
from django.tasks import task
from django.utils import timezone
from notifications.emails import MorningReportEmailArgs, send_morning_report_email
from tasks.models import Task

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
