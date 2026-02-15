from django.db import models
from django.shortcuts import get_object_or_404, render

from core.views import HttpRequest
from tasks.forms import ProjectForm
from tasks.models import Project, Task
from .board import _fetch_board_context
from .shared import SHOW_PROJECTS_QUERY_PARAM, redirect_to_board_with_query


def _project_queryset():
    return Project.objects.order_by("-is_active", "name").prefetch_related("tags")


def project_list(request: HttpRequest):
    projects = _project_queryset()
    form = ProjectForm()
    if not request.htmx:
        return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)
    return render(
        request,
        "tasks/partials/project_offcanvas_list.html",
        {"projects": projects, "form": form},
    )


def create_project(request: HttpRequest):
    if request.method == "GET":
        if not request.htmx:
            return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)
        return render(
            request,
            "tasks/partials/project_offcanvas_create.html",
            {"form": ProjectForm()},
        )

    form = ProjectForm(request.POST)
    if form.is_valid():
        form.save()
        if not request.htmx:
            return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)
        projects = _project_queryset()
        return render(
            request,
            "tasks/partials/project_offcanvas_list.html",
            {"projects": projects, "form": ProjectForm(), "saved": True},
            status=201,
        )

    if not request.htmx:
        return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)
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
                queryset=Task.objects.select_related("project").prefetch_related("tags"),
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
            return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)
    else:
        form = ProjectForm(instance=project)

    if not request.htmx:
        return redirect_to_board_with_query(SHOW_PROJECTS_QUERY_PARAM)

    return render(
        request,
        "tasks/partials/project_offcanvas_detail.html",
        {
            "form": form,
            "project": project,
            "tasks": tasks_qs,
            "saved": False,
            **(board_context or {}),
        },
        status=400 if form.errors else 200,
    )
