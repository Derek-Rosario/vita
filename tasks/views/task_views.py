from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.services import add_htmx_trigger, add_toast
from core.views import HttpRequest
from tasks.forms import CommentForm, TaskCompletionTimeForm, TaskForm
from tasks.models import Comment, Task, TaskStatus


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
    ordering = sort_field if direction == "asc" else f"-{sort_field}"

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
            task.status = TaskStatus.DONE if data.get("checked") == "on" else TaskStatus.TODO
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
        {"tasks": tasks_qs},
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
                return HttpResponse(status=204)
            if request.htmx:
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
        if request.htmx and is_autosave:
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


def prompt_task_completion_time(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)

    if request.method == "POST":
        form = TaskCompletionTimeForm(request.POST)
        if form.is_valid():
            task.status = TaskStatus.DONE
            task.completed_at = form.cleaned_data["completed_at"]
            task.save(update_fields=["status", "completed_at", "updated_at"])

            if request.htmx:
                response = HttpResponse(status=204)
                response["HX-Location"] = reverse("task_board")
                add_htmx_trigger(response, "confetti")
                return response

            return redirect("task_board")
    else:
        initial_completed_at = (
            timezone.localtime(task.completed_at)
            if task.completed_at
            else timezone.localtime()
        )
        form = TaskCompletionTimeForm(initial={"completed_at": initial_completed_at})

    return render(
        request,
        "tasks/prompt_task_completion_time.html",
        {"task": task, "form": form},
        status=400 if form.errors else 200,
    )


@require_POST
def clone_task(request: HttpRequest, task_id: int):
    original = get_object_or_404(Task, pk=task_id)
    original_tags = list(original.tags.all())
    task = original
    task.pk = None
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
