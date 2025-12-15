from __future__ import annotations

from datetime import date
from typing import Iterable, List, Optional

from django.db import models
from django.utils import timezone

from .models import Routine, RoutineStep, Task


def _weekday_sunday_first(target_date: date) -> int:
    """
    Convert Python weekday (Mon=0) to Sunday-first index (Sun=0, Sat=6).
    """
    return (target_date.weekday() + 1) % 7


def routine_is_due(routine: Routine, target_date: date) -> bool:
    """
    Determine whether a routine should run on a given date.
    """
    if not routine.is_active:
        return False

    # Explicit monthly day
    if routine.day_of_month:
        return target_date.day == routine.day_of_month

    # Day-of-week schedule
    if routine.days_of_week:
        return _weekday_sunday_first(target_date) in routine.days_of_week

    # Interval-based (anchor on created_at)
    interval = routine.interval or 1
    start_date = routine.created_at.date()
    days_since_start = (target_date - start_date).days
    return days_since_start >= 0 and days_since_start % interval == 0


def generate_tasks_for_date(
    target_date: Optional[date] = None,
    routines: Optional[Iterable[Routine]] = None,
) -> List[Task]:
    """
    Create tasks for all due routines on the given date.

    Returns the list of created tasks.
    """
    run_date = target_date or timezone.localdate()
    routines_qs = (
        Routine.objects.filter(is_active=True)
        if routines is None
        else routines
    )
    routines_qs = routines_qs.filter(is_active=True).prefetch_related(
        "steps__default_tags"
    )

    created: List[Task] = []
    for routine in routines_qs:
        if not routine_is_due(routine, run_date):
            continue

        for step in routine.steps.all().order_by("sort_order", "pk"):
            if Task.objects.filter(
                routine=routine, routine_step=step, routine_date=run_date
            ).exists():
                continue

            max_order = (
                Task.objects.filter(status=Task.Status.TODO).aggregate(
                    max_order=models.Max("order")
                )["max_order"]
                or 0
            )

            task = Task.objects.create(
                title=step.title,
                description=step.description,
                status=Task.Status.TODO,
                priority=step.default_priority,
                energy=step.default_energy,
                due_at=run_date,
                estimate_minutes=step.default_estimate_minutes or step.estimate_minutes,
                order=max_order + 1,
                routine=routine,
                routine_step=step,
                routine_date=run_date,
            )
            if step.default_tags.exists():
                task.tags.set(step.default_tags.all())
            created.append(task)

    return created
