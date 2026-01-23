from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List, Optional, cast

from django.utils import timezone
from django.db.models import BaseManager

from .models import TASK_STATUS_CATEGORY_TO_STATUSES, Routine, RoutineStep, Task, TaskStatus, TaskStatusCategory, IsAwayFromHome


def _weekday_sunday_first(target_date: date) -> int:
    """
    Convert Python weekday (Mon=0) to Sunday-first index (Sun=0, Sat=6).
    """
    return (target_date.weekday() + 1) % 7


def routine_is_due(routine: Routine, target_datetime: datetime) -> bool:
    """
    Determine whether a routine should run on a given date.
    """
    if not routine.is_active:
        return False

    # Skip if target_date is before anchor time of day, if set
    if routine.anchor_time:
        if target_datetime.time() < routine.anchor_time:
            return False

    # Explicit monthly day
    if routine.day_of_month:
        return target_datetime.day == routine.day_of_month

    # Day-of-week schedule
    if routine.days_of_week:
        return _weekday_sunday_first(target_datetime) in routine.days_of_week

    # Interval-based (anchor on created_at)
    interval = routine.interval or 1
    start_date = routine.created_at.date()
    days_since_start = (target_datetime.date() - start_date).days
    return days_since_start >= 0 and days_since_start % interval == 0


def generate_tasks_for_date(
    routines: Optional[BaseManager[Routine]] = None,
) -> List[Task]:
    """
    Create tasks for all due routines on the given date.

    Returns the list of created tasks.
    """
    run_at = timezone.localtime(timezone.now())
    run_date = timezone.localdate()

    routines_qs = (
        Routine.objects.filter(is_active=True) if routines is None else routines
    )
    routines_qs = routines_qs.filter(is_active=True).prefetch_related(
        "steps__default_tags"
    )

    # Check if there is an IsAwayFromHome instance and get its value
    is_away_from_home = IsAwayFromHome.objects.get_or_create(pk=1)[0].is_away

    created: List[Task] = []
    for routine in routines_qs:
        if not routine_is_due(routine, run_at):
            continue
        
        all_steps = cast(List[RoutineStep], routine.steps.all().order_by("sort_order", "pk"))

        for step in all_steps:

            if Task.objects.filter(
                routine=routine, routine_step=step, routine_date=run_date
            ).exists():
                continue

            if not step.is_available_away_from_home and is_away_from_home:
                continue

            # If task is not stackable, cancel any existing uncompleted tasks for this step before creating a new one
            if not step.is_stackable:
                Task.objects.filter(
                    routine=routine,
                    routine_step=step,
                    status__in=TASK_STATUS_CATEGORY_TO_STATUSES[TaskStatusCategory.TODO] + TASK_STATUS_CATEGORY_TO_STATUSES[TaskStatusCategory.IN_PROGRESS],
                ).update(status=TaskStatus.MISSED)

            task = Task.objects.create(
                title=step.title,
                description=step.description,
                status=TaskStatus.TODO,
                priority=step.default_priority,
                energy=step.default_energy,
                due_at=run_date,
                estimate_minutes=step.default_estimate_minutes or step.estimate_minutes,
                routine=routine,
                routine_step=step,
                routine_date=run_date,
            )
            if step.default_tags.exists():
                task.tags.set(step.default_tags.all())
            created.append(task)

    return created
