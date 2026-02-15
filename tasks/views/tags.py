from django.db import models
from django.shortcuts import get_object_or_404, render

from core.views import HttpRequest
from tasks.forms import TagForm
from tasks.models import Tag, Task
from .board import _fetch_board_context
from .shared import SHOW_TAGS_QUERY_PARAM, redirect_to_board_with_query


def _tag_queryset():
    return Tag.objects.annotate(task_count=models.Count("tasks")).order_by("name")


def tag_list(request: HttpRequest):
    tags = _tag_queryset()
    form = TagForm()
    if not request.htmx:
        return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)
    return render(
        request,
        "tasks/partials/tag_offcanvas_list.html",
        {"tags": tags, "form": form},
    )


def create_tag(request: HttpRequest):
    if request.method == "GET":
        if not request.htmx:
            return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)
        return render(
            request,
            "tasks/partials/tag_offcanvas_create.html",
            {"form": TagForm()},
        )

    form = TagForm(request.POST)
    if form.is_valid():
        form.save()
        if not request.htmx:
            return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)
        tags = _tag_queryset()
        return render(
            request,
            "tasks/partials/tag_offcanvas_list.html",
            {"tags": tags, "form": TagForm(), "saved": True},
            status=201,
        )

    if not request.htmx:
        return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)
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
            return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)
    else:
        form = TagForm(instance=tag)

    if not request.htmx:
        return redirect_to_board_with_query(SHOW_TAGS_QUERY_PARAM)

    return render(
        request,
        "tasks/partials/tag_offcanvas_detail.html",
        {
            "form": form,
            "tag": tag,
            "tasks": tasks_qs,
            "saved": False,
            **(board_context or {}),
        },
        status=400 if form.errors else 200,
    )
