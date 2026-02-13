import random
from typing import Dict, List
from datetime import timedelta
from datetime import datetime

from django import forms
from django.forms import inlineformset_factory
from django.db import models
from django.http import HttpResponse, QueryDict, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from django.db.models import Q

from core.models import LastGeolocation
from core.services import (
    add_htmx_trigger,
    add_toast,
    add_voice_message,
    is_close_to_home,
)
from core.views import HttpRequest
from tasks.models import (
    TASK_STATUS_CATEGORY_TO_STATUSES,
    Task,
    TaskStatus,
    TaskStatusCategory,
)
from tasks.models import Comment, Project, Routine, RoutineStep, Tag
from tasks.services import (
    generate_tasks_for_date,
    get_average_daily_completed_tasks_weight,
    get_today_completed_tasks_weight,
)
from tasks.voice import (
    TASK_BACKLOGGED_VOICE_MESSAGES,
    TASK_CANCELLED_VOICE_MESSAGES,
    TASK_COMPLETED_VOICE_MESSAGES,
)
from django.db.models import Case, Count, F, Sum, Value, When
from django.db.models.functions import TruncWeek, ExtractWeekDay

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
            "open_tags": bool(request.GET.get("show_tags")),
            "open_projects": bool(request.GET.get("show_projects")),
        },
    )


def task_list(request: HttpRequest):
    sort = request.GET.get("sort") or "created"
    direction = request.GET.get("dir") or "desc"
    sort_map = {
        "title": "title",
        "project": "project__name",
        "status": "status",
        "priority": "priority",
        "due": "due_at",
        "updated": "updated_at",
        "created": "created_at",
    }
    sort_field = sort_map.get(sort, "created_at")
    if direction == "asc":
        ordering = sort_field
    else:
        ordering = f"-{sort_field}"

    tasks_qs = (
        Task.objects.select_related("project", "parent")
        .prefetch_related("tags")
        .order_by(ordering)
    )
    paginator = Paginator(tasks_qs, 25)
    page = request.GET.get("page") or 1
    try:
        tasks_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        tasks_page = paginator.page(1)

    return render(
        request,
        "tasks/task_list.html",
        {
            "page_obj": tasks_page,
            "paginator": paginator,
            "tasks": tasks_page.object_list,
            "sort": sort,
            "direction": direction,
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


def task_checklist(request: HttpRequest):
    if request.method == "POST":
        new_task_title = request.POST.get("title", "").strip()
        if new_task_title:
            task = Task(title=new_task_title, status=TaskStatus.TODO)
            task.save()
            return render(
                request,
                "tasks/checklist.html#checklist_item",
                {"task": task},
                status=201,
            )
    elif request.method == "PATCH":
        data = QueryDict(request.body)
        if data.get("task_id"):
            task = get_object_or_404(Task, pk=int(data["task_id"]))
            if data.get("checked") == "on":
                task.status = TaskStatus.DONE
            else:
                task.status = TaskStatus.TODO
            task.save(update_fields=["status", "updated_at", "completed_at"])
            return HttpResponse(status=200)

    tasks_qs = (
        Task.objects.filter(
            status__in=[
                TaskStatus.TODO,
                TaskStatus.IN_PROGRESS,
                TaskStatus.ON_DECK,
            ]
        )
        .select_related("project", "parent")
        .prefetch_related("tags")
        .order_by("-priority", "due_at", "-created_at")
    )

    return render(
        request,
        "tasks/checklist.html#checklist" if request.htmx else "tasks/checklist.html",
        {
            "tasks": tasks_qs,
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

    # Weekly aggregation for tasks completed and completion weight.
    weight_expr = F("priority") + Case(
        When(energy="LOW", then=Value(1)),
        When(energy="MEDIUM", then=Value(2)),
        When(energy="HIGH", then=Value(3)),
        default=Value(2),
    )
    completed_base = completed_qs.annotate(week=TruncWeek("completed_at")).values(
        "week"
    )
    completed_agg = completed_base.annotate(
        tasks_completed=Count("id"),
        weight_completed=Sum(weight_expr),
    ).order_by("week")

    cancelled_base = cancelled_qs.annotate(
        week=TruncWeek("status_last_changed_at")
    ).values("week")
    cancelled_agg = cancelled_base.annotate(
        tasks_cancelled=Count("id"),
    ).order_by("week")

    created_base = created_qs.annotate(week=TruncWeek("created_at")).values("week")
    created_agg = created_base.annotate(
        tasks_created=Count("id"),
    ).order_by("week")

    labels: list[str] = []
    tasks_completed: list[int] = []
    tasks_cancelled: list[int] = []
    tasks_created: list[int] = []
    weight_completed: list[int] = []

    # Build a complete sequence of week buckets from start to now to include empty weeks.
    # Normalize weeks to Monday starts.
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
        cursor = cursor + timedelta(weeks=1)

    for row in completed_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_completed"] = int(row["tasks_completed"] or 0)
            buckets[wk]["weight_completed"] = int(row["weight_completed"] or 0)
        else:
            print("Unexpected week:", wk)

    for row in cancelled_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_cancelled"] = int(row["tasks_cancelled"] or 0)
        else:
            print("Unexpected week:", wk)

    for row in created_agg:
        wk = week_start(row["week"])
        if wk in buckets:
            buckets[wk]["tasks_created"] = int(row["tasks_created"] or 0)
        else:
            print("Unexpected week:", wk)

    # Sort by week and extract series
    for wk in sorted(buckets.keys()):
        labels.append(
            f"{wk.month}/{wk.day} - {(wk + timedelta(days=6)).month}/{(wk + timedelta(days=6)).day}"
        )
        tasks_completed.append(buckets[wk]["tasks_completed"])
        tasks_cancelled.append(buckets[wk]["tasks_cancelled"])
        tasks_created.append(buckets[wk]["tasks_created"])
        weight_completed.append(buckets[wk]["weight_completed"])

    data = {
        "labels": labels,
        "tasks_completed": tasks_completed,
        "tasks_cancelled": tasks_cancelled,
        "tasks_created": tasks_created,
        "weight_completed": weight_completed,
    }

    return JsonResponse(data)


# Helper functions
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
        # Check if home
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

    # Sort recently done column by completed_at descending
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


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "status",
            "completed_at",
            "project",
            "priority",
            "energy",
            "due_at",
            "estimate_minutes",
            "parent",
            "tags",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Details"}
            ),
            "completed_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "due_at": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "estimate_minutes": forms.NumberInput(attrs={"class": "form-control"}),
            "status": forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["completed_at"].required = False
        self.fields["completed_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ]
        self.fields["completed_at"].help_text = (
            "Adjust this if you completed the task earlier or later than it was marked done."
        )
        if self.instance.status != TaskStatus.DONE:
            self.fields.pop("completed_at")

        # Only allow active parents; show newest first for convenience.
        self.fields["parent"].queryset = Task.objects.filter(
            status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS]
        ).order_by("-created_at")
        for name in ["priority", "energy", "parent", "tags"]:
            widget = self.fields[name].widget
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-select".strip()


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["content"]
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Add a comment...",
                },
            )
        }


DAY_OF_WEEK_CHOICES = [
    (0, "Sunday"),
    (1, "Monday"),
    (2, "Tuesday"),
    (3, "Wednesday"),
    (4, "Thursday"),
    (5, "Friday"),
    (6, "Saturday"),
]


class RoutineForm(forms.ModelForm):
    days_of_week = forms.TypedMultipleChoiceField(
        required=False,
        coerce=int,
        choices=DAY_OF_WEEK_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select days for weekly cadence (optional).",
    )

    class Meta:
        model = Routine
        fields = [
            "name",
            "description",
            "tags",
            "is_active",
            "interval",
            "days_of_week",
            "day_of_month",
            "anchor_time",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Describe the routine",
                }
            ),
            "day_of_month": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 31}
            ),
            "interval": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "anchor_time": forms.TimeInput(
                attrs={"class": "form-control", "type": "time"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["tags"].widget
        css = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{css} form-select".strip()
        if self.instance and self.instance.pk and self.instance.days_of_week:
            self.initial["days_of_week"] = self.instance.days_of_week

    def clean_days_of_week(self):
        days = self.cleaned_data.get("days_of_week") or []
        return sorted(set(days))


class RoutineStepForm(forms.ModelForm):
    class Meta:
        model = RoutineStep
        fields = [
            "title",
            "description",
            "sort_order",
            "default_priority",
            "default_energy",
            "default_estimate_minutes",
            "default_tags",
            "is_stackable",
            "is_available_away_from_home",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "What happens in this step?",
                }
            ),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
            "default_estimate_minutes": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["default_priority", "default_energy", "default_tags"]:
            widget = self.fields[name].widget
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-select".strip()


RoutineStepFormSet = inlineformset_factory(
    Routine,
    RoutineStep,
    form=RoutineStepForm,
    extra=2,
    can_delete=True,
)


def edit_task(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    is_autosave = request.headers.get("HX-Target") == "task-autosave-status"
    comment_form = CommentForm()

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            if request.htmx and is_autosave:
                return HttpResponse(
                    status=204,
                )
            elif request.htmx:
                return render(
                    request,
                    "tasks/partials/task_form_card.html",
                    {
                        "form": form,
                        "task": task,
                        "saved": True,
                        "comment_form": comment_form,
                    },
                )
            return redirect("task_board")
        elif request.htmx and is_autosave:
            return HttpResponse("Failed validation.", status=400)
    else:
        form = TaskForm(instance=task)

    template = (
        "tasks/partials/task_form_card.html" if request.htmx else "tasks/task_edit.html"
    )
    return render(
        request,
        template,
        {
            "form": form,
            "task": task,
            "saved": False,
            "comment_form": comment_form,
        },
        status=400 if form.errors else 200,
    )


@require_POST
def clone_task(request: HttpRequest, task_id: int):
    original = get_object_or_404(Task, pk=task_id)
    original_tags = list(original.tags.all())
    task = original
    task.pk = None  # Reset PK to create a new instance
    task.title = f"Copy of {original.title}"
    task.status = TaskStatus.TODO
    task.completed_at = None
    task.status_last_changed_at = None
    task.created_at = timezone.now()
    task.updated_at = timezone.now()
    task.save()
    task.tags.set(original_tags)

    response = HttpResponse(status=204)
    response["HX-Location"] = reverse("edit_task", args=[task.pk])
    add_toast(
        response,
        type="success",
        message="Cloned task.",
    )
    return response


def task_activity(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    comment_form = CommentForm()
    if request.method == "POST":
        comment_form = CommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.task = task
            comment.save()

            comment_form = CommentForm()

    comments = Comment.objects.filter(task=task).order_by("-created_at")
    return render(
        request,
        "tasks/partials/task_activity_card.html",
        {
            "task": task,
            "comments": comments,
            "comment_form": comment_form,
        },
    )


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_active", "tags"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What is this project about?",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["tags"].widget
        css = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{css} form-select".strip()


def project_list(request: HttpRequest):
    projects = Project.objects.order_by("-is_active", "name").prefetch_related("tags")
    form = ProjectForm()
    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_projects=1")
    return render(
        request,
        "tasks/partials/project_offcanvas_list.html",
        {"projects": projects, "form": form},
    )


def create_project(request: HttpRequest):
    projects = Project.objects.order_by("-is_active", "name").prefetch_related("tags")
    if request.method == "GET":
        if not request.htmx:
            return redirect(f"{reverse('task_board')}?show_projects=1")
        return render(
            request,
            "tasks/partials/project_offcanvas_create.html",
            {"form": ProjectForm()},
        )

    form = ProjectForm(request.POST)
    if form.is_valid():
        form.save()
        if not request.htmx:
            return redirect(f"{reverse('task_board')}?show_projects=1")
        projects = Project.objects.order_by("-is_active", "name").prefetch_related(
            "tags"
        )
        return render(
            request,
            "tasks/partials/project_offcanvas_list.html",
            {"projects": projects, "form": ProjectForm(), "saved": True},
            status=201,
        )

    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_projects=1")
    return render(
        request,
        "tasks/partials/project_offcanvas_create.html",
        {"form": form},
        status=400 if form.errors else 200,
    )


def project_detail(request: HttpRequest, project_id: int):
    project = get_object_or_404(
        Project.objects.prefetch_related("tags").prefetch_related(
            models.Prefetch(
                "tasks",
                queryset=Task.objects.select_related("project").prefetch_related(
                    "tags"
                ),
            )
        ),
        pk=project_id,
    )
    tasks_qs = project.tasks.all()
    board_context = _fetch_board_context() if request.htmx else None
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            if request.htmx:
                return render(
                    request,
                    "tasks/partials/project_offcanvas_detail.html",
                    {
                        "form": form,
                        "project": project,
                        "tasks": tasks_qs,
                        "saved": True,
                        **(board_context or {}),
                    },
                )
            return redirect(f"{reverse('task_board')}?show_projects=1")
    else:
        form = ProjectForm(instance=project)

    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_projects=1")

    template = "tasks/partials/project_offcanvas_detail.html"
    context = {
        "form": form,
        "project": project,
        "tasks": tasks_qs,
        "saved": False,
        **(board_context or {}),
    }
    return render(
        request,
        template,
        context,
        status=400 if form.errors else 200,
    )


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "color": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "#RRGGBB (optional)"}
            ),
        }


def tag_list(request: HttpRequest):
    tags = Tag.objects.annotate(task_count=models.Count("tasks")).order_by("name")
    form = TagForm()
    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_tags=1")
    return render(
        request,
        "tasks/partials/tag_offcanvas_list.html",
        {"tags": tags, "form": form},
    )


def create_tag(request: HttpRequest):
    tags = Tag.objects.annotate(task_count=models.Count("tasks")).order_by("name")
    if request.method == "GET":
        if not request.htmx:
            return redirect(f"{reverse('task_board')}?show_tags=1")
        return render(
            request,
            "tasks/partials/tag_offcanvas_create.html",
            {"form": TagForm()},
        )

    form = TagForm(request.POST)
    if form.is_valid():
        form.save()
        if not request.htmx:
            return redirect(f"{reverse('task_board')}?show_tags=1")
        tags = Tag.objects.annotate(task_count=models.Count("tasks")).order_by("name")
        return render(
            request,
            "tasks/partials/tag_offcanvas_list.html",
            {"tags": tags, "form": TagForm(), "saved": True},
            status=201,
        )

    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_tags=1")
    return render(
        request,
        "tasks/partials/tag_offcanvas_create.html",
        {"form": form},
        status=400 if form.errors else 200,
    )


def tag_detail(request: HttpRequest, tag_id: int):
    tag = get_object_or_404(
        Tag.objects.annotate(task_count=models.Count("tasks")),
        pk=tag_id,
    )
    tasks_qs = (
        Task.objects.filter(tags=tag)
        .select_related("project")
        .prefetch_related("tags")
        .order_by("status", "-priority", "due_at", "-created_at")
    )
    board_context = _fetch_board_context() if request.htmx else None
    if request.method == "POST":
        form = TagForm(request.POST, instance=tag)
        if form.is_valid():
            form.save()
            if request.htmx:
                return render(
                    request,
                    "tasks/partials/tag_offcanvas_detail.html",
                    {
                        "form": form,
                        "tag": tag,
                        "tasks": tasks_qs,
                        "saved": True,
                        **(board_context or {}),
                    },
                )
            return redirect(f"{reverse('task_board')}?show_tags=1")
    else:
        form = TagForm(instance=tag)

    if not request.htmx:
        return redirect(f"{reverse('task_board')}?show_tags=1")

    template = "tasks/partials/tag_offcanvas_detail.html"
    return render(
        request,
        template,
        {
            "form": form,
            "tag": tag,
            "tasks": tasks_qs,
            "saved": False,
            **(board_context or {}),
        },
        status=400 if form.errors else 200,
    )


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


def catch_up(request: HttpRequest):
    if request.method == "POST":
        # Mark all listed tasks as done
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


def stats_index(request: HttpRequest):
    return {}
