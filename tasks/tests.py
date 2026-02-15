
from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
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

    def test_recalculates_when_completed_time_is_edited_on_done_task(self) -> None:
        routine = Routine.objects.create(name="Evening routine")
        step = RoutineStep.objects.create(routine=routine, title="Reflect")

        initial_time = timezone.make_aware(
            datetime(2026, 1, 1, 22, 0, 0), timezone.get_current_timezone()
        )
        corrected_time = timezone.make_aware(
            datetime(2026, 1, 1, 20, 0, 0), timezone.get_current_timezone()
        )

        task = Task.objects.create(
            title="Reflect",
            status=TaskStatus.TODO,
            routine=routine,
            routine_step=step,
        )
        task.status = TaskStatus.DONE
        task.completed_at = initial_time
        task.save(update_fields=["status", "completed_at", "updated_at"])
        step.refresh_from_db()
        self.assertEqual(step.typical_completion_time_p25, time(hour=22, minute=0))
        self.assertEqual(step.typical_completion_time_p75, time(hour=22, minute=0))

        task.completed_at = corrected_time
        task.save(update_fields=["completed_at", "updated_at"])

        step.refresh_from_db()
        self.assertEqual(step.typical_completion_time_p25, time(hour=20, minute=0))
        self.assertEqual(step.typical_completion_time_p75, time(hour=20, minute=0))


class MarkTaskDoneTests(TestCase):
    def setUp(self) -> None:
        user = get_user_model().objects.create_superuser(
            username="tester", email="tester@example.com", password="secret123"
        )
        self.client.force_login(user)

    def test_mark_done_accepts_corrected_completion_datetime(self) -> None:
        task = Task.objects.create(
            title="Write summary",
            status=TaskStatus.TODO,
            due_at=timezone.localdate() - timezone.timedelta(days=1),
        )

        response = self.client.post(
            reverse("mark_task_done", args=[task.id]),
            {"completed_at_actual": "2026-01-02T23:45"},
        )
        self.assertEqual(response.status_code, 204)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertIsNotNone(task.completed_at)
        completed_local = timezone.localtime(task.completed_at)
        self.assertEqual(completed_local.year, 2026)
        self.assertEqual(completed_local.month, 1)
        self.assertEqual(completed_local.day, 2)
        self.assertEqual(completed_local.hour, 23)
        self.assertEqual(completed_local.minute, 45)

    def test_mark_done_rejects_future_completion_datetime(self) -> None:
        task = Task.objects.create(title="Future check", status=TaskStatus.TODO)
        future_local = timezone.localtime(
            timezone.now() + timezone.timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M")

        response = self.client.post(
            reverse("mark_task_done", args=[task.id]),
            {"completed_at_actual": future_local},
        )
        self.assertEqual(response.status_code, 400)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertIsNone(task.completed_at)

    def test_prompt_completion_time_rejects_future_completion_datetime(self) -> None:
        task = Task.objects.create(title="Modal future check", status=TaskStatus.TODO)
        future_local = timezone.localtime(
            timezone.now() + timezone.timedelta(hours=2)
        ).strftime("%Y-%m-%dT%H:%M")

        response = self.client.post(
            reverse("prompt_task_completion_time", args=[task.id]),
            {"completed_at": future_local},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Completion date/time cannot be in the future.",
            status_code=400,
        )

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertIsNone(task.completed_at)
