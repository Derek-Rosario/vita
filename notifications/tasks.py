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

    in_progress_tasks = (
        Task.objects.filter(status="in_progress").order_by("-priority").all()
    )
    in_progress_count = in_progress_tasks.count()
    in_progress_points = sum(task.completion_weight for task in in_progress_tasks)

    completed_yesterday_tasks = Task.objects.filter(
        status="completed",
        completed_at__date__exact=timezone.now().date() - datetime.timedelta(days=1),
    ).all()
    completed_yesterday_count = completed_yesterday_tasks.count()
    completed_yesterday_points = sum(
        task.completion_weight for task in completed_yesterday_tasks
    )

    args = MorningReportEmailArgs(
        in_progress_count=in_progress_count,
        in_progress_points=in_progress_points,
        yesterday_comparison="more than"
        if in_progress_count > completed_yesterday_count
        else "not more than",
        completed_yesterday_count=completed_yesterday_count,
        completed_yesterday_points=completed_yesterday_points,
        in_progress_tasks=in_progress_tasks,
    )
    send_morning_report_email(args)
    return True
