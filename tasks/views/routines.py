from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.db import models
from django.db.models import Count, Q
from django.db.models.functions import ExtractWeekDay
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.views import HttpRequest
from tasks.forms import RoutineForm, RoutineStepFormSet
from tasks.models import Routine, RoutineStep, Task, TaskStatus
from tasks.services import generate_tasks_for_date, routine_is_due


def routine_list(request: HttpRequest):
    routines = (
        Routine.objects.prefetch_related("tags")
        .annotate(step_count=models.Count("steps"))
        .order_by("name")
    )
    return render(
        request,
        "tasks/routine_list.html",
        {
            "routines": routines,
            "today": timezone.localdate(),
        },
    )


def routine_create(request: HttpRequest):
    routine = Routine()
    if request.method == "POST":
        form = RoutineForm(request.POST, instance=routine)
        formset = RoutineStepFormSet(request.POST, instance=routine)
        if form.is_valid() and formset.is_valid():
            routine = form.save()
            formset.instance = routine
            formset.save()
            messages.success(request, "Routine created.")
            return redirect("routine_list")
    else:
        form = RoutineForm()
        formset = RoutineStepFormSet(instance=routine)

    return render(
        request,
        "tasks/routine_form.html",
        {
            "form": form,
            "formset": formset,
            "routine": routine,
            "is_create": True,
        },
        status=400
        if request.method == "POST" and (form.errors or formset.errors)
        else 200,
    )


def routine_edit(request: HttpRequest, routine_id: int):
    routine = get_object_or_404(
        Routine.objects.prefetch_related("steps"), pk=routine_id
    )
    if request.method == "POST":
        form = RoutineForm(request.POST, instance=routine)
        formset = RoutineStepFormSet(request.POST, instance=routine)
        if form.is_valid() and formset.is_valid():
            routine = form.save()
            formset.instance = routine
            formset.save()
            messages.success(request, "Routine updated.")
            return redirect("routine_list")
    else:
        form = RoutineForm(instance=routine)
        formset = RoutineStepFormSet(instance=routine)

    return render(
        request,
        "tasks/routine_form.html",
        {
            "form": form,
            "formset": formset,
            "routine": routine,
            "is_create": False,
        },
        status=400
        if request.method == "POST" and (form.errors or formset.errors)
        else 200,
    )


def routine_step_detail(request: HttpRequest, step_id: int):
    routine_step = get_object_or_404(
        RoutineStep.objects.select_related("routine"), pk=step_id
    )
    tasks_qs = Task.objects.filter(routine_step=routine_step).exclude(
        routine_date__isnull=True
    )

    total_count = tasks_qs.count()
    completed_count = tasks_qs.filter(status=TaskStatus.DONE).count()
    completion_rate = (
        round(completed_count / total_count * 100, 1) if total_count else 0
    )

    weekday_labels = {
        1: "Sunday",
        2: "Monday",
        3: "Tuesday",
        4: "Wednesday",
        5: "Thursday",
        6: "Friday",
        7: "Saturday",
    }

    daily_aggregates = (
        tasks_qs.annotate(weekday=ExtractWeekDay("routine_date"))
        .values("weekday")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=TaskStatus.DONE)),
        )
    )
    aggregates_map = {entry["weekday"]: entry for entry in daily_aggregates}

    daily_stats = []
    for weekday in range(1, 8):
        totals = aggregates_map.get(weekday, {"total": 0, "completed": 0})
        day_total = totals.get("total", 0)
        day_completed = totals.get("completed", 0)
        day_rate = round(day_completed / day_total * 100, 1) if day_total else 0
        daily_stats.append(
            {
                "label": weekday_labels[weekday],
                "total": day_total,
                "completed": day_completed,
                "rate": day_rate,
            }
        )

    return render(
        request,
        "tasks/routine_step_detail.html",
        {
            "routine_step": routine_step,
            "total_count": total_count,
            "completed_count": completed_count,
            "completion_rate": completion_rate,
            "daily_stats": daily_stats,
        },
    )


@require_POST
def routine_delete(request: HttpRequest, routine_id: int):
    routine = get_object_or_404(Routine, pk=routine_id)
    routine.delete()
    messages.success(request, "Routine deleted.")
    return redirect("routine_list")


def routine_schedule(request: HttpRequest):
    today = timezone.localdate()
    try:
        start_date = date.fromisoformat(request.GET.get("start", ""))
    except (ValueError, TypeError):
        start_date = today - timedelta(days=13)

    try:
        end_date = date.fromisoformat(request.GET.get("end", ""))
        if end_date < start_date:
            end_date = start_date + timedelta(days=13)
    except (ValueError, TypeError):
        end_date = start_date + timedelta(days=13)

    # Cap at 90 days to avoid performance issues
    if (end_date - start_date).days > 89:
        end_date = start_date + timedelta(days=89)

    num_days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(num_days)]

    routines = Routine.objects.prefetch_related(
        "steps__default_tags"
    ).order_by("name")

    tasks_in_range = Task.objects.filter(
        routine_date__gte=start_date,
        routine_date__lte=end_date,
        routine_step__isnull=False,
    ).select_related("routine_step")

    task_lookup: dict[tuple[int, date], Task] = {}
    for task in tasks_in_range:
        key = (task.routine_step_id, task.routine_date)
        task_lookup[key] = task

    routine_rows = []
    for routine in routines:
        steps = list(routine.steps.all().order_by("sort_order", "pk"))
        if not steps:
            continue

        step_rows = []
        for step in steps:
            cells = []
            for d in dates:
                task = task_lookup.get((step.pk, d))
                is_today = d == today
                if task is not None:
                    if task.status == TaskStatus.DONE:
                        completed_local = (
                            timezone.localtime(task.completed_at)
                            if task.completed_at
                            else None
                        )
                        cells.append(
                            {
                                "state": "done",
                                "completed_at": completed_local,
                                "is_today": is_today,
                                "date": d,
                            }
                        )
                    else:
                        cells.append(
                            {
                                "state": "missed",
                                "completed_at": None,
                                "is_today": is_today,
                                "date": d,
                            }
                        )
                else:
                    # Check if routine was due on this date (use end-of-day to
                    # satisfy any anchor_time constraint)
                    check_dt = timezone.make_aware(
                        datetime.combine(d, time(23, 59))
                    )
                    if routine_is_due(routine, check_dt):
                        cells.append(
                            {
                                "state": "missed",
                                "completed_at": None,
                                "is_today": is_today,
                                "date": d,
                            }
                        )
                    else:
                        cells.append(
                            {
                                "state": "none",
                                "completed_at": None,
                                "is_today": is_today,
                                "date": d,
                            }
                        )
            step_rows.append({"step": step, "cells": cells})

        routine_rows.append({"routine": routine, "step_rows": step_rows})

    prev_start = start_date - timedelta(days=num_days)
    prev_end = end_date - timedelta(days=num_days)
    next_start = start_date + timedelta(days=num_days)
    next_end = end_date + timedelta(days=num_days)

    return render(
        request,
        "tasks/routine_schedule.html",
        {
            "routine_rows": routine_rows,
            "dates": dates,
            "start_date": start_date,
            "end_date": end_date,
            "today": today,
            "prev_start": prev_start,
            "prev_end": prev_end,
            "next_start": next_start,
            "next_end": next_end,
        },
    )


@require_POST
def routine_run(request: HttpRequest, routine_id: int | None = None):
    routines = None
    if routine_id:
        routines = Routine.objects.filter(pk=routine_id)

    created = generate_tasks_for_date(routines=routines)
    messages.success(
        request,
        f"Created {len(created)} task(s) for {timezone.now().isoformat()}.",
    )
    return redirect("routine_list")
