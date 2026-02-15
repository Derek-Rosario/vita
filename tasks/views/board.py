from datetime import datetime
from datetime import timedelta
import logging
import random
from typing import Dict, List

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import Case, Count, F, Q, Sum, Value, When
from django.db.models.functions import TruncWeek
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import LastGeolocation
from core.services import (
    add_htmx_trigger,
    add_toast,
    add_voice_message,
    is_close_to_home,
)
from core.views import HttpRequest
from tasks.forms import TaskForm
from tasks.models import Task, TaskStatus
from tasks.services import (
    get_average_daily_completed_tasks_weight,
    get_today_completed_tasks_weight,
)
from tasks.voice import (
    TASK_BACKLOGGED_VOICE_MESSAGES,
    TASK_CANCELLED_VOICE_MESSAGES,
    TASK_COMPLETED_VOICE_MESSAGES,
)
from .shared import SHOW_PROJECTS_QUERY_PARAM, SHOW_TAGS_QUERY_PARAM

logger = logging.getLogger(__name__)

BOARD_STATUSES = [
    (TaskStatus.TODO, "To do"),
    (TaskStatus.ON_DECK, "On deck"),
    (TaskStatus.IN_PROGRESS, "In progress"),
    (TaskStatus.BLOCKED, "Blocked"),
    (TaskStatus.DONE, "Done"),
]


def task_board(request: HttpRequest):
    form = TaskForm()
    return render(
        request,
        "tasks/board.html",
        {
            **_fetch_board_context(),
            "backlog_count": Task.objects.filter(status=TaskStatus.BACKLOG).count(),
            "form": form,
            "open_tags": bool(request.GET.get(SHOW_TAGS_QUERY_PARAM)),
            "open_projects": bool(request.GET.get(SHOW_PROJECTS_QUERY_PARAM)),
        },
    )


def task_backlog(request: HttpRequest):
    """
    Backlog tasks are intentionally not shown on the Kanban board.
    Move them to "To do" to make them appear on the board.
    """
    tasks_qs = (
        Task.objects.filter(status=TaskStatus.BACKLOG)
        .select_related("project", "parent")
        .prefetch_related("tags")
        .order_by("-priority", "due_at", "-created_at")
    )
    paginator = Paginator(tasks_qs, 25)
    page = request.GET.get("page") or 1
    try:
        tasks_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        tasks_page = paginator.page(1)

    return render(
        request,
        "tasks/backlog.html",
        {
            "page_obj": tasks_page,
            "paginator": paginator,
            "tasks": tasks_page.object_list,
            "next_url": request.get_full_path(),
        },
    )


@require_POST
def promote_backlog_task(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    if task.status != TaskStatus.BACKLOG:
        messages.info(request, "Task is not in backlog.")
        return redirect("task_backlog")

    task.status = TaskStatus.TODO
    task.save(update_fields=["status", "updated_at"])
    messages.success(request, "Moved to To do.")

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("task_backlog")


@require_POST
def mark_task_done(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    if task.status == TaskStatus.DONE:
        return HttpResponse(status=204)

    completed_at_actual = request.POST.get("completed_at_actual", "").strip()
    completed_at_value = timezone.now()
    if completed_at_actual:
        try:
            parsed_value = datetime.fromisoformat(completed_at_actual)
        except ValueError:
            response = HttpResponse(status=400)
            add_toast(
                response,
                type="error",
                message="Invalid completion date/time format.",
            )
            return response

        if timezone.is_naive(parsed_value):
            parsed_value = timezone.make_aware(
                parsed_value, timezone.get_current_timezone()
            )
        completed_at_value = parsed_value

    if completed_at_value > timezone.now():
        response = HttpResponse(status=400)
        add_toast(
            response,
            type="error",
            message="Completion date/time cannot be in the future.",
        )
        return response

    task.status = TaskStatus.DONE
    task.completed_at = completed_at_value
    task.save(update_fields=["status", "updated_at", "completed_at"])

    response = HttpResponse(status=204)
    response["HX-Location"] = reverse("task_board")
    add_htmx_trigger(response, "confetti")
    return response


def board_fragment(request: HttpRequest):
    """
    Return just the board partial for HTMX refreshes.
    """
    return render(
        request,
        "tasks/partials/board.html",
        {
            **_fetch_board_context(),
            "dropped_task_pk": int(request.GET.get("updated_task_pk"))
            if request.GET.get("updated_task_pk")
            else None,
        },
    )


@require_POST
def move_task(request: HttpRequest):
    task_id = request.POST.get("task_id")
    status = request.POST.get("status")
    valid_statuses = {code for code, _ in BOARD_STATUSES}
    valid_statuses.add(TaskStatus.CANCELLED)
    valid_statuses.add(TaskStatus.BACKLOG)
    if not task_id or not status or status not in valid_statuses:
        response = HttpResponse(status=204)
        add_toast(response, type="error", message="Invalid request.")
        return response

    task = get_object_or_404(Task, pk=task_id)
    task.status = status
    update_fields = ["status", "updated_at"]
    just_completed = status == TaskStatus.DONE and task.completed_at is None
    if just_completed:
        task.completed_at = timezone.now()
        update_fields.append("completed_at")
    task.save(update_fields=update_fields)

    response = HttpResponse(status=204)

    if just_completed:
        message = random.choice(TASK_COMPLETED_VOICE_MESSAGES)
        add_toast(
            response,
            type="success",
            message=message,
        )
        add_htmx_trigger(response, "confetti")
        add_voice_message(response, message=message)
    elif status == TaskStatus.CANCELLED:
        message = random.choice(TASK_CANCELLED_VOICE_MESSAGES)
        add_toast(response, type="info", message=message)
        add_voice_message(response, message=message)
    elif status == TaskStatus.BACKLOG:
        message = random.choice(TASK_BACKLOGGED_VOICE_MESSAGES)
        add_toast(response, type="info", message=message)
        add_voice_message(response, message=message)

    return response


@require_POST
def quick_add_task(request: HttpRequest):
    title = request.POST.get("title", "").strip()
    if not title:
        response = HttpResponse(status=204)
        add_toast(response, type="error", message="Task title cannot be empty.")
        return response

    task = Task.from_text(title)
    task.save()

    response = HttpResponse(status=204)
    add_toast(
        response,
        type="success",
        message="Added task.",
    )
    return response


@require_POST
def create_task(request: HttpRequest):
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.save()
        form.save_m2m()
        response = HttpResponse(status=204)
        add_toast(
            response,
            type="success",
            message="Added task.",
        )
        return response

    response = HttpResponse(status=204)
    add_toast(
        response,
        type="error",
        message="Please check the form for errors.",
    )
    return response


@require_POST
def delete_task(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    task.delete()

    response = HttpResponse(status=204)
    response["HX-Location"] = reverse("task_board")
    add_toast(
        response,
        type="success",
        message="Deleted task.",
    )
    return response


def velocity_chart(request: HttpRequest):
    """
    Render the velocity chart page. Data is fetched from the JSON endpoint.
    """
    return render(request, "tasks/velocity.html")


def velocity_data(request: HttpRequest):
    """
    Return weekly velocity data as JSON.

    Query params:
    - weeks: int (default 12) number of weeks to include
    - project_id: optional filter to a specific project
    """
    try:
        weeks = int(request.GET.get("weeks", 12))
    except ValueError:
        weeks = 12

    now = timezone.localtime()
    start = now - timedelta(weeks=weeks)

    completed_qs = Task.objects.filter(
        status=TaskStatus.DONE, completed_at__isnull=False, completed_at__gte=start
    )
    cancelled_qs = Task.objects.filter(
        status__in=[TaskStatus.CANCELLED, TaskStatus.MISSED],
        status_last_changed_at__isnull=False,
        status_last_changed_at__gte=start,
    )
    created_qs = Task.objects.filter(created_at__gte=start)

    weight_expr = F("priority") + Case(
        When(energy="LOW", then=Value(1)),
        When(energy="MEDIUM", then=Value(2)),
        When(energy="HIGH", then=Value(3)),
        default=Value(2),
    )
    completed_agg = (
        completed_qs.annotate(week=TruncWeek("completed_at"))
        .values("week")
        .annotate(
            tasks_completed=Count("id"),
            weight_completed=Sum(weight_expr),
        )
        .order_by("week")
    )
    cancelled_agg = (
        cancelled_qs.annotate(week=TruncWeek("status_last_changed_at"))
        .values("week")
        .annotate(
            tasks_cancelled=Count("id"),
        )
        .order_by("week")
    )
    created_agg = (
        created_qs.annotate(week=TruncWeek("created_at"))
        .values("week")
        .annotate(
            tasks_created=Count("id"),
        )
        .order_by("week")
    )

    labels: list[str] = []
    tasks_completed: list[int] = []
    tasks_cancelled: list[int] = []
    tasks_created: list[int] = []
    weight_completed: list[int] = []

    def week_start(dt: datetime) -> datetime:
        return (dt - timedelta(days=dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    buckets: dict[datetime, dict] = {}
    cursor = week_start(start)
    end = week_start(now)
    while cursor <= end:
        buckets[cursor] = {
            "tasks_completed": 0,
            "tasks_cancelled": 0,
            "tasks_created": 0,
            "weight_completed": 0,
        }
        cursor += timedelta(weeks=1)

    for row in completed_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_completed"] = int(row["tasks_completed"] or 0)
            buckets[wk]["weight_completed"] = int(row["weight_completed"] or 0)
        else:
            logger.warning("Unexpected completed week bucket: %s", wk)

    for row in cancelled_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_cancelled"] = int(row["tasks_cancelled"] or 0)
        else:
            logger.warning("Unexpected cancelled week bucket: %s", wk)

    for row in created_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_created"] = int(row["tasks_created"] or 0)
        else:
            logger.warning("Unexpected created week bucket: %s", wk)

    for wk in sorted(buckets.keys()):
        labels.append(
            f"{wk.month}/{wk.day} - {(wk + timedelta(days=6)).month}/{(wk + timedelta(days=6)).day}"
        )
        tasks_completed.append(buckets[wk]["tasks_completed"])
        tasks_cancelled.append(buckets[wk]["tasks_cancelled"])
        tasks_created.append(buckets[wk]["tasks_created"])
        weight_completed.append(buckets[wk]["weight_completed"])

    return JsonResponse(
        {
            "labels": labels,
            "tasks_completed": tasks_completed,
            "tasks_cancelled": tasks_cancelled,
            "tasks_created": tasks_created,
            "weight_completed": weight_completed,
        }
    )


def _fetch_board_context():
    cutoff = timezone.now() - timedelta(days=2)
    tasks = (
        Task.objects.filter(status__in=[code for code, _ in BOARD_STATUSES])
        .filter(
            models.Q(status=TaskStatus.DONE, completed_at__gte=cutoff)
            | ~models.Q(status=TaskStatus.DONE)
        )
        .select_related("parent", "project")
        .prefetch_related("tags")
        .order_by("-priority", "due_at", "-created_at")
    )

    is_away_from_home: bool | None = None
    last_geolocation = LastGeolocation.objects.first()
    if last_geolocation and last_geolocation.is_fresh:
        is_away_from_home = is_close_to_home(
            last_geolocation.latitude, last_geolocation.longitude
        )
        if not is_away_from_home:
            tasks = tasks.exclude(routine_step__is_available_away_from_home=False)

    grouped: Dict[TaskStatus | str, List[Task]] = {
        code: [] for code, _ in BOARD_STATUSES
    }
    for task in tasks:
        grouped[task.status].append(task)

    grouped[TaskStatus.DONE].sort(
        key=lambda t: t.completed_at or timezone.now(), reverse=True
    )

    columns = [
        {
            "code": code,
            "label": label,
            "tasks": grouped.get(code, []),
            "total_weight": sum(t.completion_weight for t in grouped.get(code, [])),
        }
        for code, label in BOARD_STATUSES
    ]

    today_completed_tasks_weight = get_today_completed_tasks_weight()
    average_daily_completed_tasks_weight = round(
        get_average_daily_completed_tasks_weight() * 1.5
    )

    return {
        "columns": columns,
        "today_completed_tasks_weight": today_completed_tasks_weight,
        "average_daily_completed_tasks_weight": average_daily_completed_tasks_weight,
        "today_completed_tasks_weight_percent": (
            today_completed_tasks_weight / average_daily_completed_tasks_weight * 100
        )
        if average_daily_completed_tasks_weight
        else 0,
        "is_away_from_home": is_away_from_home,
    }


def catch_up(request: HttpRequest):
    if request.method == "POST":
        task_id = request.POST.get("task_id")
        status = request.POST.get("status")
        task = get_object_or_404(Task, pk=task_id)
        task.status = status
        task.status_last_confirmed_at = timezone.now()
        task.save()

    all_incomplete_board_tasks_not_recently_updated = Task.objects.filter(
        Q(status_last_confirmed_at__lt=timezone.now() - timedelta(days=1))
        | Q(status_last_confirmed_at__isnull=True),
        status__in=[code for code, _ in BOARD_STATUSES if code != TaskStatus.DONE],
    )

    return render(
        request,
        "tasks/catch_up.html#content" if request.htmx else "tasks/catch_up.html",
        {
            "all_incomplete_board_tasks_not_recently_updated": all_incomplete_board_tasks_not_recently_updated,
            "statuses": TaskStatus.choices,
        },
    )
