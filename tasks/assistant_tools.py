from __future__ import annotations

from datetime import date, time
from typing import Any

from django.db import transaction
from django.utils import timezone

from assistant.tools import ToolContext, ToolDefinition, ToolResult
from tasks.models import Project, Routine, Task, TaskStatus
from tasks.services import generate_tasks_for_date

VALID_TASK_STATUSES = {choice for choice, _ in TaskStatus.choices}
VALID_TASK_PRIORITIES = {choice for choice, _ in Task.Priority.choices}
VALID_TASK_ENERGIES = {choice for choice, _ in Task.Energy.choices}


def get_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="tasks_list_tasks",
            description="List tasks with optional filters.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": sorted(VALID_TASK_STATUSES)},
                    "include_done": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=_tasks_list_tasks,
        ),
        ToolDefinition(
            name="tasks_create_task",
            description="Create a task.",
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
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=_tasks_update_task,
        ),
        ToolDefinition(
            name="tasks_delete_task",
            description="Delete a task by id.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "integer", "minimum": 1}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=_tasks_delete_task,
        ),
        ToolDefinition(
            name="tasks_list_routines",
            description="List routines with optional filters.",
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
            name="tasks_delete_routine",
            description="Delete a routine by id.",
            input_schema={
                "type": "object",
                "properties": {"routine_id": {"type": "integer", "minimum": 1}},
                "required": ["routine_id"],
                "additionalProperties": False,
            },
            handler=_tasks_delete_routine,
        ),
        ToolDefinition(
            name="tasks_run_routine",
            description="Generate tasks for one routine or all active routines.",
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
    status = _parse_task_status(args.get("status"))
    include_done = _as_bool(args.get("include_done"), field="include_done", default=True)
    limit = _as_int(args.get("limit"), field="limit", minimum=1, maximum=50, default=20)

    queryset = Task.objects.select_related("project", "parent", "routine").order_by(
        "-updated_at"
    )
    if status:
        queryset = queryset.filter(status=status)
    elif not include_done:
        queryset = queryset.exclude(status=TaskStatus.DONE)

    tasks = list(queryset[:limit])
    return ToolResult(
        ok=True,
        data={
            "count": len(tasks),
            "tasks": [_serialize_task(task) for task in tasks],
        },
    )


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

    if "title" in args:
        task.title = _parse_required_text(args.get("title"), field="title")
        changed = True
    if "description" in args:
        task.description = _parse_optional_text(
            args.get("description"), field="description"
        ) or ""
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
        if project_id is not None and not Project.objects.filter(pk=project_id).exists():
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

    if changed:
        with transaction.atomic():
            task.save()

    return ToolResult(
        ok=True,
        message="Task updated." if changed else "No changes applied.",
        data={"task": _serialize_task(task)},
    )


def _tasks_delete_task(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    task_id = _as_int(args.get("task_id"), field="task_id", minimum=1, required=True)
    task = Task.objects.filter(pk=task_id).first()
    if task is None:
        raise ValueError(f"Task {task_id} does not exist.")
    task.delete()
    return ToolResult(
        ok=True,
        message="Task deleted.",
        data={"deleted_task_id": task_id},
    )


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
    day_of_month = _as_int(args.get("day_of_month"), field="day_of_month", minimum=1, maximum=31)
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
        routine.description = _parse_optional_text(
            args.get("description"), field="description"
        ) or ""
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


def _tasks_delete_routine(args: dict[str, Any], context: ToolContext) -> ToolResult:
    _require_superuser(context)
    routine_id = _as_int(
        args.get("routine_id"), field="routine_id", minimum=1, required=True
    )
    routine = Routine.objects.filter(pk=routine_id).first()
    if routine is None:
        raise ValueError(f"Routine {routine_id} does not exist.")
    routine.delete()
    return ToolResult(
        ok=True,
        message="Routine deleted.",
        data={"deleted_routine_id": routine_id},
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


def _require_superuser(context: ToolContext) -> None:
    user = context.user
    if not getattr(user, "is_authenticated", False):
        raise PermissionError("Authentication is required.")
    if not getattr(user, "is_superuser", False):
        raise PermissionError("Superuser permission is required.")


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


def _parse_days_of_week(value: Any) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("days_of_week must be a list of integers between 0 and 6.")

    days: list[int] = []
    for item in value:
        day = _as_int(item, field="days_of_week item", minimum=0, maximum=6, required=True)
        days.append(day)
    return sorted(set(days))


def _validate_routine_schedule(
    *,
    days_of_week: list[int] | None,
    day_of_month: int | None,
) -> None:
    if days_of_week and day_of_month is not None:
        raise ValueError("Use either days_of_week or day_of_month, not both.")


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
