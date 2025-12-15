from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from tasks.models import Routine
from tasks.services import generate_tasks_for_date


class Command(BaseCommand):
    help = "Generate tasks from active routines for a given date."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--date",
            dest="date",
            help="Target date in YYYY-MM-DD format (defaults to today).",
        )
        parser.add_argument(
            "--routine",
            dest="routine_ids",
            action="append",
            type=int,
            help="Specific routine ID to run (can be provided multiple times).",
        )

    def handle(self, *args, **options) -> None:
        date_str = options.get("date")
        routine_ids = options.get("routine_ids")

        target_date = timezone.localdate()
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD."))
                return

        routines = None
        if routine_ids:
            routines = Routine.objects.filter(pk__in=routine_ids)

        created = generate_tasks_for_date(target_date=target_date, routines=routines)
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(created)} task(s) for {target_date.isoformat()}."
            )
        )
