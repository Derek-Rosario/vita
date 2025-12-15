from django.contrib import admin

from .models import Comment, Project, Routine, RoutineStep, Tag, Task


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "created_at", "updated_at")
    search_fields = ("name",)


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("content",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status",
        "priority",
        "due_at",
        "completed_at",
        "is_active",
    )
    list_filter = ("status", "priority", "energy", "tags")
    search_fields = ("title", "description")
    autocomplete_fields = ("parent", "tags", "routine", "routine_step")
    inlines = (CommentInline,)
    ordering = ("status", "-priority", "due_at", "-created_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "archived_at", "created_at", "updated_at")
    list_filter = ("is_active", "tags")
    search_fields = ("name", "description")
    autocomplete_fields = ("tags",)


class RoutineStepInline(admin.TabularInline):
    model = RoutineStep
    extra = 0
    autocomplete_fields = ("default_tags",)
    fields = (
        "title",
        "description",
        "sort_order",
        "default_priority",
        "default_estimate_minutes",
        "default_energy",
        "default_tags",
    )


@admin.register(Routine)
class RoutineAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "interval", "anchor_time", "created_at")
    list_filter = ("is_active", "tags")
    search_fields = ("name", "description")
    autocomplete_fields = ("tags",)
    inlines = (RoutineStepInline,)


@admin.register(RoutineStep)
class RoutineStepAdmin(admin.ModelAdmin):
    list_display = ("routine", "title", "sort_order", "default_priority")
    list_filter = ("routine",)
    search_fields = ("title", "description")
    autocomplete_fields = ("routine", "default_tags")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("task", "content", "created_at")
    search_fields = ("content",)
    autocomplete_fields = ("task",)
