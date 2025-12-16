from django.db import models
from django.utils import timezone
from core.models import TimestampedModel


class Tag(TimestampedModel):
    name = models.CharField(
        max_length=50,
        unique=True,
        help_text="Label name.",
    )
    color = models.CharField(
        blank=True,
        help_text="Optional CSS color name for UI accents.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Project(TimestampedModel):
    tags = models.ManyToManyField(
        "Tag",
        related_name="projects",
        blank=True,
        help_text="Labels for this project.",
    )

    name = models.CharField(
        max_length=255,
        help_text="Project name.",
    )
    description = models.TextField(
        blank=True,
        help_text="Brief project description.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether the project is currently in use.",
    )
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the project was archived.",
    )

    def __str__(self):
        return self.name


class Task(TimestampedModel):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        CANCELLED = "cancelled", "Cancelled"
        DONE = "done", "Done"

    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"
        URGENT = 4, "Urgent"

    class Energy(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    title = models.CharField(
        max_length=255, help_text="Short task title.", default="New task"
    )
    description = models.TextField(
        blank=True,
        help_text="Details or context for the task.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
        help_text="Current workflow state.",
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices,
        default=Priority.NORMAL,
        help_text="Importance level.",
    )

    # Scheduling / planning
    due_at = models.DateField(
        null=True,
        blank=True,
        help_text="Due date for completion.",
    )
    estimate_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Estimated effort in minutes.",
    )

    energy = models.CharField(
        max_length=8,
        choices=Energy.choices,
        default=Energy.MEDIUM,
        help_text="Energy level needed.",
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the task was completed.",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
        help_text="Project this task belongs to.",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subtasks",
        help_text="Parent task when nested.",
    )
    tags = models.ManyToManyField(
        "Tag",
        related_name="tasks",
        blank=True,
        help_text="Labels attached to this task.",
    )

    # Routine association
    routine = models.ForeignKey(
        "tasks.Routine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_tasks",
        help_text="Routine that produced this task.",
    )
    routine_step = models.ForeignKey(
        "tasks.RoutineStep",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_tasks",
        help_text="Routine step that produced this task.",
    )
    routine_date = models.DateField(
        null=True,
        blank=True,
        help_text="Day the routine instance belongs to.",
    )
    promoted_from_routine = models.BooleanField(
        default=False,
        help_text="True if explicitly kept from the routine.",
    )  # if you explicitly "keep" it

    class Meta:
        ordering = ["status", "-priority", "due_at", "-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["due_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        set_completed = self.status == Task.Status.DONE and self.completed_at is None
        if set_completed:
            self.completed_at = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                fields = set(update_fields)
                fields.add("completed_at")
                kwargs["update_fields"] = list(fields)
        clear_completed = (
            self.status != Task.Status.DONE and self.completed_at is not None
        )
        if clear_completed:
            self.completed_at = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                fields = set(update_fields)
                fields.add("completed_at")
                kwargs["update_fields"] = list(fields)
        super().save(*args, **kwargs)

    @property
    def is_routine_task(self) -> bool:
        return self.routine is not None

    @property
    def is_subtask(self) -> bool:
        return self.parent is not None

    @property
    def has_subtasks(self) -> bool:
        return self.subtasks.exists()

    @property
    def is_active(self) -> bool:
        return self.status not in {Task.Status.DONE, Task.Status.CANCELLED}

    @property
    def is_overdue(self) -> bool:
        return (
            self.status != Task.Status.DONE
            and self.due_at is not None
            and self.due_at < timezone.now()
        )


class Comment(TimestampedModel):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        help_text="Task this comment belongs to.",
    )
    content = models.TextField(
        help_text="Comment text.",
    )

    def __str__(self) -> str:
        return self.content


class Routine(TimestampedModel):
    name = models.CharField(
        max_length=255,
        help_text="Routine name.",
    )
    description = models.TextField(
        blank=True,
        help_text="What the routine covers.",
    )
    tags = models.ManyToManyField(
        "Tag",
        blank=True,
        related_name="routines",
        help_text="Labels applied to this routine.",
    )

    # Recurrence pattern
    days_of_week = models.JSONField(
        null=True,
        blank=True,
        help_text="Day indexes for recurrence (0=Sun, 6=Sat).",
        default=list,
    )
    day_of_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Day of month (1-31) for monthly routines.",
    )
    interval = models.PositiveSmallIntegerField(
        default=1,
        help_text="Frequency interval (e.g., every 2 days).",
    )

    # optional anchor time (e.g., 08:00 for morning routine)
    anchor_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Optional anchor time (e.g., 08:00).",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether the routine is currently used.",
    )

    def __str__(self):
        return self.name

    @property
    def schedule_display(self) -> str:
        day_labels = [
            "Sunday",
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
        ]
        if self.days_of_week:
            selected = [
                day_labels[idx]
                for idx in self.days_of_week
                if 0 <= idx < len(day_labels)
            ]
            return f"Weekly: {', '.join(selected)}"
        if self.day_of_month:
            return f"Day {self.day_of_month} each month"
        interval = self.interval or 1
        suffix = "day" if interval == 1 else "days"
        return f"Every {interval} {suffix}"


class RoutineStep(TimestampedModel):
    routine = models.ForeignKey(
        Routine,
        on_delete=models.CASCADE,
        related_name="steps",
        help_text="Routine this step belongs to.",
    )

    # Defaults for tasks created from this step
    title = models.CharField(
        max_length=255,
        help_text="Step title.",
    )
    description = models.TextField(
        blank=True,
        help_text="What happens in this step.",
    )
    estimate_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Estimated minutes for this step.",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order within the routine.",
    )

    default_priority = models.IntegerField(
        choices=Task.Priority.choices,
        default=Task.Priority.NORMAL,
        help_text="Default priority for generated tasks.",
    )
    default_estimate_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Default estimate in minutes.",
    )
    default_tags = models.ManyToManyField(
        "Tag",
        blank=True,
        related_name="routine_steps",
        help_text="Default tags for generated tasks.",
    )
    default_energy = models.CharField(
        max_length=8,
        choices=Task.Energy.choices,
        default=Task.Energy.MEDIUM,
        help_text="Default energy level for generated tasks.",
    )

    def __str__(self):
        return f"{self.routine.name}: {self.title}"
