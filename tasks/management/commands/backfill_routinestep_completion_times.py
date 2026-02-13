from django.core.management.base import BaseCommand

from tasks.models import RoutineStep


class Command(BaseCommand):
    help = (
        "Backfill RoutineStep typical completion time percentiles (p25 and p75) "
        "from completed routine tasks."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--step-id",
            type=int,
            help="Optional RoutineStep id to backfill only a single step.",
        )

    def handle(self, *args, **options) -> None:
        step_id = options.get("step_id")

        queryset = RoutineStep.objects.all().order_by("id")
        if step_id is not None:
            queryset = queryset.filter(id=step_id)

        if not queryset.exists():
            self.stdout.write(self.style.WARNING("No RoutineStep records found."))
            return

        processed = 0
        for step in queryset.iterator():
            step.recalculate_typical_completion_times()
            processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfilled typical completion percentiles for {processed} routine step(s)."
            )
        )
