from __future__ import annotations

from datetime import date, time
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import LastGeolocation
from core.services import is_close_to_home
from assistant.tools import ToolContext, ToolDefinition, ToolResult
from tasks.models import (
    Comment,
    Project,
    Routine,
    RoutineStep,
    ScheduledAwayTrip,
    Tag,
    Task,
    TaskStatus,
)
from tasks.services import generate_tasks_for_date

VALID_TASK_STATUSES = {choice for choice, _ in TaskStatus.choices}
VALID_TASK_PRIORITIES = {choice for choice, _ in Task.Priority.choices}
VALID_TASK_ENERGIES = {choice for choice, _ in Task.Energy.choices}
AWAY_FILTER_DESCRIPTION = (
    "When away from home, this defaults to away-compatible tasks unless "
    "include_all_locations is true."
)
INCLUDE_ALL_LOCATIONS_SCHEMA = {
    "type": "boolean",
    "description": "Set true to include all tasks even when user is away from home.",
}
TODO_WHEN_TO_USE = ""  # TODO: Add user intents/situations that should trigger this tool.
TODO_WHEN_NOT_TO_USE = ""  # TODO: Add exclusions/guardrails for when this tool should not run.


def get_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="tasks_list_tasks",
            description=f"List tasks with optional filters. {AWAY_FILTER_DESCRIPTION}",
            when_to_use=(
                "User asks for tasks to do now or asks to find/search tasks by keyword."
            ),
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Optional keyword to match against title/description text."
                        ),
                    },
                    "status": {"type": "string", "enum": sorted(VALID_TASK_STATUSES)},
                    "include_done": {"type": "boolean"},
                    "include_all_locations": INCLUDE_ALL_LOCATIONS_SCHEMA,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=_tasks_list_tasks,
        ),
        ToolDefinition(
            name="tasks_create_task",
            description="Create a task.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": sorted(VALID_TASK_STATUSES)},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 4},
                    "energy": {"type": "string", "enum": sorted(VALID_TASK_ENERGIES)},
                    "due_at": {"type": "string", "description": "YYYY-MM-DD"},
                    "estimate_minutes": {"type": "integer", "minimum": 0},
                    "project_id": {"type": "integer", "minimum": 1},
                    "parent_id": {"type": "integer", "minimum": 1},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            handler=_tasks_create_task,
        ),
        ToolDefinition(
            name="tasks_update_task",
            description="Update task fields.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": sorted(VALID_TASK_STATUSES)},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 4},
                    "energy": {"type": "string", "enum": sorted(VALID_TASK_ENERGIES)},
                    "due_at": {
                        "anyOf": [
                            {"type": "string", "description": "YYYY-MM-DD"},
                            {"type": "null"},
                        ]
                    },
                    "estimate_minutes": {
                        "anyOf": [
                            {"type": "integer", "minimum": 0},
                            {"type": "null"},
                        ]
                    },
                    "project_id": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1},
                            {"type": "null"},
                        ]
                    },
                    "parent_id": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1},
                            {"type": "null"},
                        ]
                    },
                    "tag_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "tag_mode": {
                        "type": "string",
                        "enum": ["set", "add", "remove"],
                        "description": "How to apply provided tags. Defaults to 'set'.",
                    },
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=_tasks_update_task,
        ),
        ToolDefinition(
            name="tasks_add_comment",
            description="Add a comment to a task.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "minimum": 1},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["task_id", "content"],
                "additionalProperties": False,
            },
            handler=_tasks_add_comment,
        ),
        ToolDefinition(
            name="tasks_create_tag",
            description="Create a new task tag.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "color": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=_tasks_create_tag,
        ),
        ToolDefinition(
            name="tasks_list_tags",
            description="List task tags with optional search filters.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Optional keyword to match against name/description text."
                        ),
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=_tasks_list_tags,
        ),
        ToolDefinition(
            name="tasks_list_routines",
            description="List routines with optional filters.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=_tasks_list_routines,
        ),
        ToolDefinition(
            name="tasks_create_routine",
            description="Create a routine.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "interval": {"type": "integer", "minimum": 1},
                    "days_of_week": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    },
                    "day_of_month": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1, "maximum": 31},
                            {"type": "null"},
                        ]
                    },
                    "anchor_time": {
                        "anyOf": [
                            {"type": "string", "description": "HH:MM or HH:MM:SS"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=_tasks_create_routine,
        ),
        ToolDefinition(
            name="tasks_update_routine",
            description="Update routine fields.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "routine_id": {"type": "integer", "minimum": 1},
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "interval": {"type": "integer", "minimum": 1},
                    "days_of_week": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    },
                    "day_of_month": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1, "maximum": 31},
                            {"type": "null"},
                        ]
                    },
                    "anchor_time": {
                        "anyOf": [
                            {"type": "string", "description": "HH:MM or HH:MM:SS"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["routine_id"],
                "additionalProperties": False,
            },
            handler=_tasks_update_routine,
        ),
        ToolDefinition(
            name="tasks_list_routine_steps",
            description="List steps for a routine.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "routine_id": {"type": "integer", "minimum": 1},
                },
                "required": ["routine_id"],
                "additionalProperties": False,
            },
            handler=_tasks_list_routine_steps,
        ),
        ToolDefinition(
            name="tasks_create_routine_step",
            description="Create a routine step.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "routine_id": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "sort_order": {"type": "integer", "minimum": 0},
                    "default_priority": {"type": "integer", "minimum": 1, "maximum": 4},
                    "default_energy": {
                        "type": "string",
                        "enum": sorted(VALID_TASK_ENERGIES),
                    },
                    "default_estimate_minutes": {"type": "integer", "minimum": 0},
                    "is_stackable": {"type": "boolean"},
                    "is_available_away_from_home": {"type": "boolean"},
                    "default_tag_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
                "required": ["routine_id", "title"],
                "additionalProperties": False,
            },
            handler=_tasks_create_routine_step,
        ),
        ToolDefinition(
            name="tasks_update_routine_step",
            description="Update routine step fields.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {
                    "routine_step_id": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "sort_order": {"type": "integer", "minimum": 0},
                    "default_priority": {"type": "integer", "minimum": 1, "maximum": 4},
                    "default_energy": {
                        "type": "string",
                        "enum": sorted(VALID_TASK_ENERGIES),
                    },
                    "default_estimate_minutes": {
                        "anyOf": [
                            {"type": "integer", "minimum": 0},
                            {"type": "null"},
                        ]
                    },
                    "is_stackable": {"type": "boolean"},
                    "is_available_away_from_home": {"type": "boolean"},
                    "default_tag_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
                "required": ["routine_step_id"],
                "additionalProperties": False,
            },
            handler=_tasks_update_routine_step,
        ),
        ToolDefinition(
            name="tasks_run_routine",
            description="Generate tasks for one routine or all active routines.",
            when_to_use=TODO_WHEN_TO_USE,
            when_not_to_use=TODO_WHEN_NOT_TO_USE,
            input_schema={
                "type": "object",
                "properties": {"routine_id": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
            handler=_tasks_run_routine,
        ),
    ]


def _tasks_list_tasks(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    query = _parse_optional_text(args.get("query"), field="query")
    if query == "":
        raise ValueError("query cannot be empty.")
    status, include_done, include_all_locations, limit = _parse_task_query_args(args)
    queryset, away_context = _build_task_queryset(
        status=status,
        include_done=include_done,
        include_all_locations=include_all_locations,
        query=query,
    )

    tasks = list(queryset[:limit])
    data: dict[str, Any] = {
        "count": len(tasks),
        **away_context,
        "tasks": [_serialize_task(task) for task in tasks],
    }
    if query is not None:
        data["query"] = query
    return ToolResult(
        ok=True,
        data=data,
    )


def _parse_task_query_args(args: dict[str, Any]) -> tuple[str | None, bool, bool, int]:
    status = _parse_task_status(args.get("status"))
    include_done = _as_bool(
        args.get("include_done"), field="include_done", default=True
    )
    include_all_locations = _as_bool(
        args.get("include_all_locations"), field="include_all_locations", default=False
    )
    limit = _as_int(args.get("limit"), field="limit", minimum=1, maximum=50, default=20)
    return status, include_done, include_all_locations, limit


def _build_task_queryset(
    *,
    status: str | None,
    include_done: bool,
    include_all_locations: bool,
    query: str | None = None,
):
    is_away_from_home, away_context_source = _resolve_away_from_home_status()
    applied_away_filter = is_away_from_home is True and not include_all_locations

    queryset = Task.objects.select_related(
        "project", "parent", "routine", "routine_step"
    ).order_by("-updated_at")
    if query is not None:
        queryset = queryset.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )
    if status:
        queryset = queryset.filter(status=status)
    elif not include_done:
        queryset = queryset.exclude(status=TaskStatus.DONE)
    if applied_away_filter:
        queryset = queryset.filter(routine_step__is_available_away_from_home=True)

    away_context = {
        "is_away_from_home": is_away_from_home,
        "away_context_source": away_context_source,
        "applied_away_from_home_filter": applied_away_filter,
        "include_all_locations": include_all_locations,
    }
    return queryset, away_context


def _tasks_create_task(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    title = _parse_required_text(args.get("title"), field="title")
    description = _parse_optional_text(args.get("description"), field="description")
    status = _parse_task_status(args.get("status"))
    priority = _parse_task_priority(args.get("priority"))
    energy = _parse_task_energy(args.get("energy"))
    due_at = _parse_date(args.get("due_at"), field="due_at")
    estimate_minutes = _as_int(
        args.get("estimate_minutes"), field="estimate_minutes", minimum=0
    )

    task = Task(title=title)
    if description is not None:
        task.description = description
    if status:
        task.status = status
    if priority is not None:
        task.priority = priority
    if energy:
        task.energy = energy
    if due_at is not None:
        task.due_at = due_at
    if estimate_minutes is not None:
        task.estimate_minutes = estimate_minutes

    if "project_id" in args:
        project_id = _as_int(args.get("project_id"), field="project_id", minimum=1)
        if project_id is not None:
            if not Project.objects.filter(pk=project_id).exists():
                raise ValueError(f"Project {project_id} does not exist.")
            task.project_id = project_id

    if "parent_id" in args:
        parent_id = _as_int(args.get("parent_id"), field="parent_id", minimum=1)
        if parent_id is not None:
            if not Task.objects.filter(pk=parent_id).exists():
                raise ValueError(f"Parent task {parent_id} does not exist.")
            task.parent_id = parent_id

    with transaction.atomic():
        task.save()

    return ToolResult(
        ok=True,
        message="Task created.",
        data={"task": _serialize_task(task)},
    )


def _tasks_update_task(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    task_id = _as_int(args.get("task_id"), field="task_id", minimum=1, required=True)
    task = Task.objects.filter(pk=task_id).first()
    if task is None:
        raise ValueError(f"Task {task_id} does not exist.")

    changed = False
    tag_update_requested = "tag_ids" in args
    tag_mode = "set"
    tags: list[Tag] = []

    if "title" in args:
        task.title = _parse_required_text(args.get("title"), field="title")
        changed = True
    if "description" in args:
        task.description = (
            _parse_optional_text(args.get("description"), field="description") or ""
        )
        changed = True
    if "status" in args:
        task.status = _parse_task_status(args.get("status"), required=True)
        changed = True
    if "priority" in args:
        task.priority = _parse_task_priority(args.get("priority"), required=True)
        changed = True
    if "energy" in args:
        task.energy = _parse_task_energy(args.get("energy"), required=True)
        changed = True
    if "due_at" in args:
        task.due_at = _parse_date(args.get("due_at"), field="due_at")
        changed = True
    if "estimate_minutes" in args:
        task.estimate_minutes = _as_int(
            args.get("estimate_minutes"), field="estimate_minutes", minimum=0
        )
        changed = True
    if "project_id" in args:
        project_id = _as_int(args.get("project_id"), field="project_id", minimum=1)
        if (
            project_id is not None
            and not Project.objects.filter(pk=project_id).exists()
        ):
            raise ValueError(f"Project {project_id} does not exist.")
        task.project_id = project_id
        changed = True
    if "parent_id" in args:
        parent_id = _as_int(args.get("parent_id"), field="parent_id", minimum=1)
        if parent_id is not None:
            if parent_id == task.id:
                raise ValueError("A task cannot be its own parent.")
            if not Task.objects.filter(pk=parent_id).exists():
                raise ValueError(f"Parent task {parent_id} does not exist.")
        task.parent_id = parent_id
        changed = True
    if tag_update_requested:
        tag_ids = _parse_int_list(args.get("tag_ids"), field="tag_ids")
        if tag_ids is None:
            raise ValueError("tag_ids is required when updating task tags.")
        tag_mode = _parse_tag_update_mode(args.get("tag_mode"), field="tag_mode")
        tags = _load_tags(tag_ids)

    with transaction.atomic():
        if changed:
            task.save()
        if tag_update_requested:
            if tag_mode == "set":
                task.tags.set(tags)
            elif tag_mode == "add":
                if tags:
                    task.tags.add(*tags)
            elif tag_mode == "remove":
                if tags:
                    task.tags.remove(*tags)

    payload: dict[str, Any] = {"task": _serialize_task(task)}
    if tag_update_requested:
        task = Task.objects.prefetch_related("tags").get(pk=task_id)
        payload["tag_mode"] = tag_mode
        payload["tag_ids"] = list(task.tags.values_list("id", flat=True))
        payload["tags"] = [_serialize_tag(tag) for tag in task.tags.all().order_by("name")]
    return ToolResult(
        ok=True,
        message="Task updated." if (changed or tag_update_requested) else "No changes applied.",
        data=payload,
    )


def _tasks_add_comment(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    task_id = _as_int(args.get("task_id"), field="task_id", minimum=1, required=True)
    content = _parse_required_text(args.get("content"), field="content")

    task = Task.objects.filter(pk=task_id).first()
    if task is None:
        raise ValueError(f"Task {task_id} does not exist.")

    with transaction.atomic():
        comment = Comment.objects.create(task=task, content=content)

    return ToolResult(
        ok=True,
        message="Comment added.",
        data={
            "comment": {
                "id": comment.id,
                "task_id": task.id,
                "content": comment.content,
                "created_at": timezone.localtime(comment.created_at).isoformat(),
            }
        },
    )


def _tasks_create_tag(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    name = _parse_required_text(args.get("name"), field="name")
    color = _parse_optional_text(args.get("color"), field="color")
    description = _parse_optional_text(args.get("description"), field="description")

    existing = Tag.objects.filter(name__iexact=name).first()
    if existing is not None:
        return ToolResult(
            ok=True,
            message="Tag already exists.",
            data={"created": False, "tag": _serialize_tag(existing)},
        )

    tag = Tag(name=name)
    if color is not None:
        tag.color = color
    if description is not None:
        tag.description = description

    with transaction.atomic():
        tag.save()

    return ToolResult(
        ok=True,
        message="Tag created.",
        data={"created": True, "tag": _serialize_tag(tag)},
    )


def _tasks_list_tags(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    query = _parse_optional_text(args.get("query"), field="query")
    if query == "":
        raise ValueError("query cannot be empty.")
    limit = _as_int(args.get("limit"), field="limit", minimum=1, maximum=50, default=20)

    queryset = Tag.objects.order_by("name")
    if query is not None:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    tags = list(queryset[:limit])

    data: dict[str, Any] = {
        "count": len(tags),
        "tags": [_serialize_tag(tag) for tag in tags],
    }
    if query is not None:
        data["query"] = query

    return ToolResult(ok=True, data=data)


def _tasks_list_routines(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    active_only = _as_bool(args.get("active_only"), field="active_only", default=False)
    limit = _as_int(args.get("limit"), field="limit", minimum=1, maximum=50, default=20)

    queryset = Routine.objects.prefetch_related("steps").order_by("name")
    if active_only:
        queryset = queryset.filter(is_active=True)
    routines = list(queryset[:limit])

    return ToolResult(
        ok=True,
        data={
            "count": len(routines),
            "routines": [_serialize_routine(routine) for routine in routines],
        },
    )


def _tasks_create_routine(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    name = _parse_required_text(args.get("name"), field="name")
    description = _parse_optional_text(args.get("description"), field="description")
    interval = _as_int(args.get("interval"), field="interval", minimum=1)
    day_of_month = _as_int(
        args.get("day_of_month"), field="day_of_month", minimum=1, maximum=31
    )
    days_of_week = _parse_days_of_week(args.get("days_of_week"))
    anchor_time = _parse_time(args.get("anchor_time"), field="anchor_time")
    is_active = _as_bool(args.get("is_active"), field="is_active", default=True)

    _validate_routine_schedule(days_of_week=days_of_week, day_of_month=day_of_month)

    routine = Routine(name=name, is_active=is_active)
    if description is not None:
        routine.description = description
    if interval is not None:
        routine.interval = interval
    if day_of_month is not None:
        routine.day_of_month = day_of_month
    if days_of_week is not None:
        routine.days_of_week = days_of_week
    if anchor_time is not None:
        routine.anchor_time = anchor_time

    with transaction.atomic():
        routine.save()

    return ToolResult(
        ok=True,
        message="Routine created.",
        data={"routine": _serialize_routine(routine)},
    )


def _tasks_update_routine(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    routine_id = _as_int(
        args.get("routine_id"), field="routine_id", minimum=1, required=True
    )
    routine = Routine.objects.filter(pk=routine_id).first()
    if routine is None:
        raise ValueError(f"Routine {routine_id} does not exist.")

    changed = False

    if "name" in args:
        routine.name = _parse_required_text(args.get("name"), field="name")
        changed = True
    if "description" in args:
        routine.description = (
            _parse_optional_text(args.get("description"), field="description") or ""
        )
        changed = True
    if "is_active" in args:
        routine.is_active = _as_bool(
            args.get("is_active"), field="is_active", required=True
        )
        changed = True
    if "interval" in args:
        routine.interval = _as_int(
            args.get("interval"), field="interval", minimum=1, required=True
        )
        changed = True
    if "day_of_month" in args:
        routine.day_of_month = _as_int(
            args.get("day_of_month"), field="day_of_month", minimum=1, maximum=31
        )
        changed = True
    if "days_of_week" in args:
        routine.days_of_week = _parse_days_of_week(args.get("days_of_week")) or []
        changed = True
    if "anchor_time" in args:
        routine.anchor_time = _parse_time(args.get("anchor_time"), field="anchor_time")
        changed = True

    _validate_routine_schedule(
        days_of_week=routine.days_of_week,
        day_of_month=routine.day_of_month,
    )

    if changed:
        with transaction.atomic():
            routine.save()

    return ToolResult(
        ok=True,
        message="Routine updated." if changed else "No changes applied.",
        data={"routine": _serialize_routine(routine)},
    )


def _tasks_list_routine_steps(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    routine_id = _as_int(
        args.get("routine_id"), field="routine_id", minimum=1, required=True
    )
    routine = Routine.objects.filter(pk=routine_id).first()
    if routine is None:
        raise ValueError(f"Routine {routine_id} does not exist.")

    steps = list(
        RoutineStep.objects.filter(routine_id=routine_id)
        .prefetch_related("default_tags")
        .order_by("sort_order", "id")
    )
    return ToolResult(
        ok=True,
        data={
            "routine_id": routine_id,
            "count": len(steps),
            "steps": [_serialize_routine_step(step) for step in steps],
        },
    )


def _tasks_create_routine_step(
    args: dict[str, Any], context: ToolContext
) -> ToolResult:
    _require_superuser(context)
    routine_id = _as_int(
        args.get("routine_id"), field="routine_id", minimum=1, required=True
    )
    routine = Routine.objects.filter(pk=routine_id).first()
    if routine is None:
        raise ValueError(f"Routine {routine_id} does not exist.")

    title = _parse_required_text(args.get("title"), field="title")
    description = _parse_optional_text(args.get("description"), field="description")
    sort_order = _as_int(args.get("sort_order"), field="sort_order", minimum=0)
    default_priority = _parse_task_priority(args.get("default_priority"))
    default_energy = _parse_task_energy(args.get("default_energy"))
    default_estimate_minutes = _as_int(
        args.get("default_estimate_minutes"),
        field="default_estimate_minutes",
        minimum=0,
    )
    is_stackable = _as_bool(
        args.get("is_stackable"), field="is_stackable", default=False
    )
    is_available_away_from_home = _as_bool(
        args.get("is_available_away_from_home"),
        field="is_available_away_from_home",
        default=True,
    )
    tag_ids = _parse_int_list(args.get("default_tag_ids"), field="default_tag_ids")

    step = RoutineStep(routine=routine, title=title)
    if description is not None:
        step.description = description
    if sort_order is not None:
        step.sort_order = sort_order
    if default_priority is not None:
        step.default_priority = default_priority
    if default_energy is not None:
        step.default_energy = default_energy
    if default_estimate_minutes is not None:
        step.default_estimate_minutes = default_estimate_minutes
    step.is_stackable = is_stackable
    step.is_available_away_from_home = is_available_away_from_home

    with transaction.atomic():
        step.save()
        if tag_ids is not None:
            tags = _load_tags(tag_ids)
            step.default_tags.set(tags)

    return ToolResult(
        ok=True,
        message="Routine step created.",
        data={"routine_step": _serialize_routine_step(step)},
    )


def _tasks_update_routine_step(
    args: dict[str, Any], context: ToolContext
) -> ToolResult:
    _require_superuser(context)
    step_id = _as_int(
        args.get("routine_step_id"), field="routine_step_id", minimum=1, required=True
    )
    step = (
        RoutineStep.objects.filter(pk=step_id).prefetch_related("default_tags").first()
    )
    if step is None:
        raise ValueError(f"Routine step {step_id} does not exist.")

    changed = False
    if "title" in args:
        step.title = _parse_required_text(args.get("title"), field="title")
        changed = True
    if "description" in args:
        step.description = (
            _parse_optional_text(args.get("description"), field="description") or ""
        )
        changed = True
    if "sort_order" in args:
        step.sort_order = _as_int(
            args.get("sort_order"), field="sort_order", minimum=0, required=True
        )
        changed = True
    if "default_priority" in args:
        step.default_priority = _parse_task_priority(
            args.get("default_priority"), required=True
        )
        changed = True
    if "default_energy" in args:
        step.default_energy = _parse_task_energy(
            args.get("default_energy"), required=True
        )
        changed = True
    if "default_estimate_minutes" in args:
        step.default_estimate_minutes = _as_int(
            args.get("default_estimate_minutes"),
            field="default_estimate_minutes",
            minimum=0,
        )
        changed = True
    if "is_stackable" in args:
        step.is_stackable = _as_bool(
            args.get("is_stackable"), field="is_stackable", required=True
        )
        changed = True
    if "is_available_away_from_home" in args:
        step.is_available_away_from_home = _as_bool(
            args.get("is_available_away_from_home"),
            field="is_available_away_from_home",
            required=True,
        )
        changed = True

    with transaction.atomic():
        if changed:
            step.save()

        if "default_tag_ids" in args:
            tag_ids = _parse_int_list(
                args.get("default_tag_ids"), field="default_tag_ids"
            )
            tags = _load_tags(tag_ids or [])
            step.default_tags.set(tags)
            changed = True

    return ToolResult(
        ok=True,
        message="Routine step updated." if changed else "No changes applied.",
        data={"routine_step": _serialize_routine_step(step)},
    )


def _tasks_run_routine(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    routine_id = _as_int(args.get("routine_id"), field="routine_id", minimum=1)

    routines = None
    if routine_id is not None:
        routines = Routine.objects.filter(pk=routine_id)
        if not routines.exists():
            raise ValueError(f"Routine {routine_id} does not exist.")

    created = generate_tasks_for_date(routines=routines)
    return ToolResult(
        ok=True,
        message=f"Created {len(created)} task(s).",
        data={
            "created_count": len(created),
            "created_task_ids": [task.id for task in created],
        },
    )


def _serialize_task(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "energy": task.energy,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "estimate_minutes": task.estimate_minutes,
        "project_id": task.project_id,
        "parent_id": task.parent_id,
        "routine_id": task.routine_id,
        "routine_step_id": task.routine_step_id,
        "is_available_away_from_home": (
            task.routine_step.is_available_away_from_home if task.routine_step else None
        ),
        "completed_at": timezone.localtime(task.completed_at).isoformat()
        if task.completed_at
        else None,
        "created_at": timezone.localtime(task.created_at).isoformat(),
        "updated_at": timezone.localtime(task.updated_at).isoformat(),
    }


def _serialize_routine(routine: Routine) -> dict[str, Any]:
    return {
        "id": routine.id,
        "name": routine.name,
        "description": routine.description,
        "is_active": routine.is_active,
        "interval": routine.interval,
        "days_of_week": routine.days_of_week or [],
        "day_of_month": routine.day_of_month,
        "anchor_time": routine.anchor_time.isoformat() if routine.anchor_time else None,
        "step_count": routine.steps.count(),
        "total_estimate_minutes": routine.total_estimate_minutes,
    }


def _serialize_tag(tag: Tag) -> dict[str, Any]:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "description": tag.description,
    }


def _serialize_routine_step(step: RoutineStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "routine_id": step.routine_id,
        "title": step.title,
        "description": step.description,
        "sort_order": step.sort_order,
        "default_priority": step.default_priority,
        "default_energy": step.default_energy,
        "default_estimate_minutes": step.default_estimate_minutes,
        "is_stackable": step.is_stackable,
        "is_available_away_from_home": step.is_available_away_from_home,
        "default_tag_ids": list(step.default_tags.values_list("id", flat=True)),
        "typical_completion_time_p25": (
            step.typical_completion_time_p25.isoformat()
            if step.typical_completion_time_p25
            else None
        ),
        "typical_completion_time_p75": (
            step.typical_completion_time_p75.isoformat()
            if step.typical_completion_time_p75
            else None
        ),
    }


def _require_superuser(context: ToolContext) -> None:
    user = context.user
    if not getattr(user, "is_authenticated", False):
        raise PermissionError("Authentication is required.")
    if not getattr(user, "is_superuser", False):
        raise PermissionError("Superuser permission is required.")


def _resolve_away_from_home_status() -> tuple[bool | None, str]:
    if ScheduledAwayTrip.is_active_now():
        return True, "scheduled_trip"

    last_geolocation = LastGeolocation.objects.order_by("-updated_at").first()
    if last_geolocation and last_geolocation.is_fresh:
        return (
            not is_close_to_home(last_geolocation.latitude, last_geolocation.longitude),
            "last_geolocation",
        )

    return None, "unknown"


def _parse_tag_update_mode(value: Any, *, field: str = "tag_mode") -> str:
    if value is None:
        return "set"
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    mode = value.strip().lower()
    if mode not in {"set", "add", "remove"}:
        raise ValueError(f"{field} must be one of: set, add, remove.")
    return mode


def _parse_required_text(value: Any, *, field: str) -> str:
    text = _parse_optional_text(value, field=field)
    if text is None:
        raise ValueError(f"{field} is required.")
    if not text:
        raise ValueError(f"{field} cannot be empty.")
    return text


def _parse_optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    return value.strip()


def _parse_task_status(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("status is required.")
        return None
    if not isinstance(value, str):
        raise ValueError("status must be a string.")
    status = value.strip()
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid status '{status}'.")
    return status


def _parse_task_priority(value: Any, *, required: bool = False) -> int | None:
    parsed = _as_int(value, field="priority", minimum=1, maximum=4, required=required)
    if parsed is None:
        return None
    if parsed not in VALID_TASK_PRIORITIES:
        raise ValueError(f"Invalid priority '{parsed}'.")
    return parsed


def _parse_task_energy(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError("energy is required.")
        return None
    if not isinstance(value, str):
        raise ValueError("energy must be a string.")
    energy = value.strip().upper()
    if energy not in VALID_TASK_ENERGIES:
        raise ValueError(f"Invalid energy '{energy}'.")
    return energy


def _parse_date(value: Any, *, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD format.") from exc


def _parse_time(value: Any, *, field: str) -> time | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a time string.")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use HH:MM or HH:MM:SS format.") from exc


def _parse_int_list(value: Any, *, field: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of integers.")

    parsed_values: list[int] = []
    for item in value:
        parsed = _as_int(item, field=f"{field} item", minimum=1, required=True)
        parsed_values.append(parsed)
    return sorted(set(parsed_values))


def _parse_days_of_week(value: Any) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("days_of_week must be a list of integers between 0 and 6.")

    days: list[int] = []
    for item in value:
        day = _as_int(
            item, field="days_of_week item", minimum=0, maximum=6, required=True
        )
        days.append(day)
    return sorted(set(days))


def _validate_routine_schedule(
    *,
    days_of_week: list[int] | None,
    day_of_month: int | None,
) -> None:
    if days_of_week and day_of_month is not None:
        raise ValueError("Use either days_of_week or day_of_month, not both.")


def _load_tags(tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []

    tags = list(Tag.objects.filter(pk__in=tag_ids))
    found_ids = {tag.id for tag in tags}
    missing = [tag_id for tag_id in tag_ids if tag_id not in found_ids]
    if missing:
        missing_list = ", ".join(str(tag_id) for tag_id in missing)
        raise ValueError(f"Unknown tag id(s): {missing_list}.")
    return tags


def _as_bool(
    value: Any,
    *,
    field: str,
    required: bool = False,
    default: bool | None = None,
) -> bool:
    if value is None:
        if required and default is None:
            raise ValueError(f"{field} is required.")
        if default is None:
            return False
        return default

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field} must be a boolean.")


def _as_int(
    value: Any,
    *,
    field: str,
    minimum: int | None = None,
    maximum: int | None = None,
    required: bool = False,
    default: int | None = None,
) -> int | None:
    if value is None:
        if required and default is None:
            raise ValueError(f"{field} is required.")
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc

    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field} must be >= {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field} must be <= {maximum}.")
    return parsed
