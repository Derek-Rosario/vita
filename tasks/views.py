import json
from typing import Dict, List
from datetime import timedelta
from datetime import datetime

from django import forms
from django.forms import inlineformset_factory
from django.db import models
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages

from core.services import add_toast
from core.views import HttpRequest
from tasks.models import Task
from tasks.models import Comment, Project, Routine, RoutineStep, Tag
from tasks.services import generate_tasks_for_date

BOARD_STATUSES = [
    (Task.Status.TODO, "To do"),
    (Task.Status.IN_PROGRESS, "In progress"),
    (Task.Status.BLOCKED, "Blocked"),
    (Task.Status.DONE, "Recently done"),
]


def task_board(request: HttpRequest):
    form = TaskForm()
    return render(
        request,
        "tasks/board.html",
        {
            **_fetch_board_context(),
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


def board_fragment(request: HttpRequest):
    """
    Return just the board partial for HTMX refreshes.
    """
    return render(
        request,
        "tasks/partials/board.html",
        {**_fetch_board_context()},
    )


@require_POST
def move_task(request: HttpRequest):
    task_id = request.POST.get("task_id")
    status = request.POST.get("status")
    valid_statuses = {code for code, _ in BOARD_STATUSES}
    if not task_id or not status or status not in valid_statuses:
        return render(
            request,
            "tasks/partials/board.html",
            {**_fetch_board_context(), "error": "Invalid request."},
            status=400,
        )

    task = get_object_or_404(Task, pk=task_id)
    task.status = status
    update_fields = ["status", "updated_at"]
    just_completed = status == Task.Status.DONE and task.completed_at is None
    if just_completed:
        task.completed_at = timezone.now()
        update_fields.append("completed_at")
    task.save(update_fields=update_fields)

    response = render(
        request,
        "tasks/partials/board.html",
        {**_fetch_board_context(), "dropped_task_pk": task.pk},
    )

    if just_completed:
        add_toast(
            response,
            type="success",
            message="Nice job buddy.",
        )

    return response


@require_POST
def create_task(request: HttpRequest):
    form = TaskForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.save()
        form.save_m2m()
        context = {
            **_fetch_board_context(),
            "form": TaskForm(),
            "saved": True,
            "swap_board": True,
        }
        template = (
            "tasks/partials/add_task_form.html" if request.htmx else "tasks/board.html"
        )
        response = render(request, template, context, status=201)
        add_toast(
            response,
            type="success",
            message="Added task.",
        )

        return response
    context = {
        **_fetch_board_context(),
        "form": form,
        "saved": False,
        "swap_board": request.htmx,
    }
    template = (
        "tasks/partials/add_task_form.html" if request.htmx else "tasks/board.html"
    )
    return render(
        request,
        template,
        context,
        status=400 if form.errors else 200,
    )


# Helper functions
def _fetch_board_context():
    cutoff = timezone.now() - timedelta(days=14)
    tasks = (
        Task.objects.filter(status__in=[code for code, _ in BOARD_STATUSES])
        .filter(
            models.Q(status=Task.Status.DONE, completed_at__gte=cutoff)
            | ~models.Q(status=Task.Status.DONE)
        )
        .select_related("parent", "project")
        .prefetch_related("tags")
        .order_by("-priority", "due_at", "-created_at")
    )
    grouped: Dict[Task.Status | str, List[Task]] = {
        code: [] for code, _ in BOARD_STATUSES
    }
    for task in tasks:
        grouped[task.status].append(task)

    columns = [
        {"code": code, "label": label, "tasks": grouped.get(code, [])}
        for code, label in BOARD_STATUSES
    ]
    return {"columns": columns}


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "status",
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
            "due_at": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "estimate_minutes": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["status", "priority", "energy", "parent", "tags"]:
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
                }
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
        # If the POST is for comments
        if "content" in request.POST and "title" not in request.POST:
            comment_form = CommentForm(request.POST)
            form = TaskForm(instance=task)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.task = task
                comment.save()
                if request.htmx:
                    return render(
                        request,
                        "tasks/partials/task_comments.html",
                        {"task": task, "comment_form": CommentForm()},
                    )
                return redirect("edit_task", task_id=task.pk)
        else:
            form = TaskForm(request.POST, instance=task)
            if form.is_valid():
                form.save()
                if request.htmx and is_autosave:
                    return HttpResponse(
                        status=204,
                        headers={
                            "HX-Trigger": json.dumps(
                                {
                                    "toastMessage": {
                                        "type": "success",
                                        "message": "Saved task.",
                                    }
                                }
                            )
                        },
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


@require_POST
def routine_delete(request: HttpRequest, routine_id: int):
    routine = get_object_or_404(Routine, pk=routine_id)
    routine.delete()
    messages.success(request, "Routine deleted.")
    return redirect("routine_list")


@require_POST
def routine_run(request: HttpRequest, routine_id: int | None = None):
    date_str = request.POST.get("date")
    target_date = timezone.localdate()
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Invalid date format. Use YYYY-MM-DD.")
            return redirect("routine_list")

    routines = None
    if routine_id:
        routines = Routine.objects.filter(pk=routine_id)

    created = generate_tasks_for_date(target_date=target_date, routines=routines)
    messages.success(
        request,
        f"Created {len(created)} task(s) for {target_date.isoformat()}.",
    )
    return redirect("routine_list")
