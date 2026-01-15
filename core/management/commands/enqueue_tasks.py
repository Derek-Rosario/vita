from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser
from notifications.tasks import (
    send_morning_report_email_task,
    send_inactivity_notification_if_applicable_task,
    send_long_in_progress_tasks_notification_task,
)
from tasks.tasks import run_routines
from social.tasks import recalculate_contact_strengths

supported_tasks = {
    "run_routines": run_routines,
    "send_morning_report_email": send_morning_report_email_task,
    "recalculate_contact_strengths": recalculate_contact_strengths,
    "send_inactivity_notification_if_applicable": send_inactivity_notification_if_applicable_task,
    "send_long_in_progress_tasks_notification": send_long_in_progress_tasks_notification_task,
}


class Command(BaseCommand):
    help = "Enqueue background tasks."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--task",
            dest="task_names",
            action="append",
            type=str,
            help="Specific task name to run (can be provided multiple times).",
        )

    def handle(self, *args, **options) -> None:
        task_names = options.get("task_names")
        if task_names:
            for task_name in task_names:
                task_func = supported_tasks.get(task_name)
                if task_func:
                    self.stdout.write(f"Enqueueing task: {task_name}")
                    task_func.enqueue()
                else:
                    self.stdout.write(
                        self.style.ERROR(f"Unsupported task: {task_name}")
                    )
        else:
            self.stdout.write(self.style.WARNING("No task names provided."))
