from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Optional, cast

from django.utils import timezone
from django.db.models.manager import BaseManager

from .models import (
    TASK_STATUS_CATEGORY_TO_STATUSES,
    Routine,
    RoutineStep,
    Task,
    TaskStatus,
    TaskStatusCategory,
    ScheduledAwayTrip,
)


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

    # Skip if target_date is before anchor time of day
    anchor_time = routine.anchor_time or time(6, 0)
    if target_datetime.time() < anchor_time:
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

    is_on_trip = ScheduledAwayTrip.is_active_now()

    created: List[Task] = []
    for routine in routines_qs:
        if not routine_is_due(routine, run_at):
            continue

        all_steps = cast(
            List[RoutineStep], routine.steps.all().order_by("sort_order", "pk")
        )

        for step in all_steps:
            if Task.objects.filter(
                routine=routine, routine_step=step, routine_date=run_date
            ).exists():
                continue

            # If task is not stackable, cancel any existing uncompleted tasks for this step before creating a new one
            if not step.is_stackable:
                Task.objects.filter(
                    routine=routine,
                    routine_step=step,
                    status__in=[
                        TaskStatus.TODO,
                        TaskStatus.ON_DECK,
                        TaskStatus.IN_PROGRESS,
                        TaskStatus.BLOCKED,
                    ],
                ).update(status=TaskStatus.MISSED)

            if not step.is_available_away_from_home and is_on_trip:
                continue

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


def get_average_daily_completed_tasks_weight():
    days = 30
    yesterday = timezone.now() - timedelta(days=1)
    cutoff = yesterday - timedelta(days=days)
    completed = Task.objects.filter(
        status=TaskStatus.DONE,
        completed_at__gte=cutoff,
        completed_at__lte=yesterday,
    )

    buckets: dict[date, int] = {}
    for task in completed:
        if not task.completed_at:
            continue
        completed_date = timezone.localtime(task.completed_at).date()
        buckets[completed_date] = (
            buckets.get(completed_date, 0) + task.completion_weight
        )

    print(buckets)
    if len(buckets) == 0:
        return 0
    return round(sum(buckets.values()) / len(buckets))


def get_today_completed_tasks_weight():
    today = timezone.localdate()
    completed = Task.objects.filter(
        status=TaskStatus.DONE,
        completed_at__date=today,
    )

    total_weight = 0
    for task in completed:
        total_weight += task.completion_weight

    return total_weight
