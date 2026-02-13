
from datetime import datetime, time

from django.test import TestCase
from django.utils import timezone

from tasks.models import Routine, RoutineStep, Task, TaskStatus


class RoutineStepCompletionPercentilesTests(TestCase):
    def test_recalculates_p25_and_p75_when_task_marked_completed(self) -> None:
        routine = Routine.objects.create(name="Morning routine")
        step = RoutineStep.objects.create(routine=routine, title="Hydrate")

        completion_times = (
            datetime(2026, 1, 1, 8, 0, 0),
            datetime(2026, 1, 2, 10, 0, 0),
            datetime(2026, 1, 3, 12, 0, 0),
            datetime(2026, 1, 4, 14, 0, 0),
        )

        for index, completion_dt in enumerate(completion_times):
            task = Task.objects.create(
                title=f"Hydrate {index}",
                status=TaskStatus.TODO,
                routine=routine,
                routine_step=step,
            )
            task.status = TaskStatus.DONE
            task.completed_at = timezone.make_aware(
                completion_dt, timezone.get_current_timezone()
            )
            task.save(update_fields=["status", "completed_at", "updated_at"])

        step.refresh_from_db()

        self.assertEqual(step.typical_completion_time_p25, time(hour=9, minute=30))
        self.assertEqual(step.typical_completion_time_p75, time(hour=12, minute=30))
