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
from tasks.services import generate_tasks_for_date


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
