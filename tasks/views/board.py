from datetime import datetime
from datetime import timedelta
import json
import logging
import random
import re
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
from assistant.services.llm import ChatMessage, ChatRequest
from assistant.services.llm.factory import get_provider
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
QUICK_ADD_LLM_PROMPT = (
    "You enrich task metadata. Return only a JSON object with keys: "
    "estimate_minutes (integer), priority (1-4), energy (LOW|MEDIUM|HIGH), "
    "description (short string)."
)
QUICK_ADD_LOG_PREVIEW_LENGTH = 240


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

    dropped_task_pk = request.GET.get("updated_task_pk")
    try:
        dropped_task_pk = int(dropped_task_pk) if dropped_task_pk else None
    except ValueError:
        dropped_task_pk = None

    return render(
        request,
        "tasks/partials/board.html",
        {
            **_fetch_board_context(),
            "dropped_task_pk": dropped_task_pk,
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
    logger.info(
        "Quick-add received: user_id=%s has_at_prefix=%s title='%s'",
        getattr(request.user, "id", None),
        title.startswith("@"),
        _preview_text(title),
    )
    if not title:
        response = HttpResponse(status=204)
        add_toast(response, type="error", message="Task title cannot be empty.")
        return response

    try:
        task = _build_quick_add_task(title)
    except ValueError as exc:
        logger.warning("Quick-add rejected: reason='%s' title='%s'", exc, title)
        response = HttpResponse(status=204)
        add_toast(response, type="error", message=str(exc))
        return response
    task.save()
    logger.info(
        "Quick-add saved: task_id=%s title='%s' priority=%s energy=%s estimate_minutes=%s description_len=%s",
        task.id,
        _preview_text(task.title),
        task.priority,
        task.energy,
        task.estimate_minutes,
        len(task.description or ""),
    )

    response = HttpResponse(status=204)
    add_toast(
        response,
        type="success",
        message="Added task.",
    )
    return response


def _build_quick_add_task(title: str) -> Task:
    if not title.startswith("@"):
        logger.info(
            "Quick-add using default parsing (no @ prefix): title='%s'",
            _preview_text(title),
        )
        return Task.from_text(title)

    normalized_title = title[1:].strip()
    logger.info(
        "Quick-add @ task detected: raw_title='%s' normalized_title='%s'",
        _preview_text(title),
        _preview_text(normalized_title),
    )
    if not normalized_title:
        raise ValueError("Task title cannot be empty.")

    task = Task.from_text(normalized_title)
    enrichment = _enrich_quick_add_task_with_llm(normalized_title)
    if enrichment:
        logger.info(
            "Quick-add enrichment applied: title='%s' fields=%s",
            _preview_text(normalized_title),
            sorted(enrichment.keys()),
        )
        if "estimate_minutes" in enrichment:
            task.estimate_minutes = enrichment["estimate_minutes"]
        if "priority" in enrichment:
            task.priority = enrichment["priority"]
        if "energy" in enrichment:
            task.energy = enrichment["energy"]
        if "description" in enrichment:
            task.description = enrichment["description"]
    else:
        logger.warning(
            "Quick-add enrichment unavailable; falling back to defaults: title='%s'",
            _preview_text(normalized_title),
        )
    logger.info(
        "Quick-add @ result: title='%s' priority=%s energy=%s estimate_minutes=%s description_len=%s",
        _preview_text(task.title),
        task.priority,
        task.energy,
        task.estimate_minutes,
        len(task.description or ""),
    )
    return task


def _enrich_quick_add_task_with_llm(title: str) -> dict[str, int | str] | None:
    try:
        logger.info(
            "Quick-add enrichment calling LLM for title='%s'", _preview_text(title)
        )
        provider = get_provider()
        response = provider.chat(
            ChatRequest(
                messages=[
                    ChatMessage(role="system", content=QUICK_ADD_LLM_PROMPT),
                    ChatMessage(role="user", content=title),
                ],
                max_output_tokens=200,
            )
        )
        logger.debug(
            "Quick-add enrichment raw LLM response for '%s': %s",
            (_preview_text(title), _preview_text(response.content)),
        )
        payload = _extract_json_object(response.content)
        if payload is None:
            logger.warning(
                "Quick-add enrichment returned no parseable JSON for title='%s'. LLM response: %s",
                _preview_text(title),
                response.content,
            )
            return None
        normalized = _normalize_quick_add_enrichment(payload)
        if not normalized:
            logger.warning(
                "Quick-add enrichment JSON parsed but no valid fields remained for title='%s': payload=%s",
                _preview_text(title),
                payload,
            )
            return None
        logger.info(
            "Quick-add enrichment normalized for title='%s': %s",
            _preview_text(title),
            normalized,
        )
        return normalized
    except Exception:  # noqa: BLE001
        logger.exception("Quick-add LLM enrichment failed for title '%s'.", title)
        return None


def _extract_json_object(content: str) -> dict | None:
    text = content.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def _normalize_quick_add_enrichment(payload: dict) -> dict[str, int | str]:
    normalized: dict[str, int | str] = {}

    estimate = payload.get("estimate_minutes")
    if estimate is not None:
        try:
            estimate_int = int(estimate)
        except (TypeError, ValueError):
            estimate_int = None
        if estimate_int is not None and 0 <= estimate_int <= 24 * 60:
            normalized["estimate_minutes"] = estimate_int

    priority = payload.get("priority")
    if priority is not None:
        try:
            priority_int = int(priority)
        except (TypeError, ValueError):
            priority_int = None
        if priority_int in {choice for choice, _ in Task.Priority.choices}:
            normalized["priority"] = priority_int

    energy = payload.get("energy")
    if isinstance(energy, str):
        energy_value = energy.strip().upper()
        if energy_value in {choice for choice, _ in Task.Energy.choices}:
            normalized["energy"] = energy_value

    description = payload.get("description")
    if isinstance(description, str):
        description_value = description.strip()
        if description_value:
            normalized["description"] = description_value[:280]

    return normalized


def _preview_text(
    text: str | None, *, limit: int = QUICK_ADD_LOG_PREVIEW_LENGTH
) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


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
