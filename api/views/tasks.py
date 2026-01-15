import json

from django.http import HttpResponse

from core.views import HttpRequest
from tasks.models import Task, TaskStatus


def list_tasks(request: HttpRequest) -> HttpResponse:
    """
    API endpoint to retrieve a list of tasks in JSON format.
    Supports optional filtering by project, tag, and status.
    """

    tasks = (
        Task.objects.all()
        .select_related("project")
        .prefetch_related("tags")
        .prefetch_related("comments")
        .prefetch_related("subtasks")
        .select_related("parent")
        .order_by("created_at", "due_at", "priority")
    )

    # Filtering by status
    status = request.GET.get("status")
    if status:
        tasks = tasks.filter(status=status)

    records = []
    for task in tasks:
        record = {
            "id": task.pk,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "estimate_minutes": task.estimate_minutes,
            "energy": task.energy,
            "completed_at": task.completed_at.isoformat()
            if task.completed_at
            else None,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "project": {
                "id": task.project.pk,
                "name": task.project.name,
            }
            if task.project
            else None,
            "tags": [{"id": tag.pk, "name": tag.name} for tag in task.tags.all()],
            "comments": [
                {
                    "id": comment.pk,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                }
                for comment in task.comments.all()
            ],
        }
        records.append(record)

    return HttpResponse(json.dumps(records), content_type="application/json")
