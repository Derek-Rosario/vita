from datetime import date, timedelta

from django.http import HttpRequest as HttpRequestBase
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_htmx.middleware import HtmxDetails

from core.models import LastGeolocation
from core.services import add_htmx_trigger, add_toast
from journal.models import JournalEntry, MoodChoices, MoodEntry
from tasks.models import Task, TaskStatus


class HttpRequest(HttpRequestBase):
    htmx: HtmxDetails


def day_overview(request: HttpRequest):
    selected_date = _parse_date_param(request.GET.get("date"))

    open_tasks = _get_open_tasks()
    journal_entry = _get_journal_entry(selected_date)
    mood_entries = _get_mood_entries(selected_date)

    return render(
        request,
        "core/day_overview.html",
        {
            "selected_date": selected_date,
            "prev_date": selected_date - timedelta(days=1),
            "next_date": selected_date + timedelta(days=1),
            "is_today": selected_date == timezone.localdate(),
            "open_tasks": open_tasks,
            "journal_entry": journal_entry,
            "mood_entries": mood_entries,
            "mood_choices": MoodChoices.choices,
        },
    )


@require_POST
def day_overview_mark_task_done(request: HttpRequest, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    date_str = request.POST.get("date")
    selected_date = _parse_date_param(date_str)

    task.status = TaskStatus.DONE
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "updated_at", "completed_at"])

    open_tasks = _get_open_tasks()
    response = render(
        request,
        "core/partials/day_tasks_tile.html",
        {
            "selected_date": selected_date,
            "open_tasks": open_tasks,
        },
    )
    add_htmx_trigger(response, "confetti")
    return response


def day_overview_journal(request: HttpRequest):
    date_str = request.GET.get("date") or request.POST.get("date")
    selected_date = _parse_date_param(date_str)
    journal_entry = _get_journal_entry(selected_date)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content_markdown", "").strip()
        if not title:
            title = selected_date.strftime("%B %-d, %Y")

        if journal_entry:
            journal_entry.title = title
            journal_entry.content_markdown = content
            journal_entry.save(update_fields=["title", "content_markdown", "updated_at"])
        else:
            journal_entry = JournalEntry.objects.create(
                date=selected_date,
                title=title,
                content_markdown=content,
            )

        response = render(
            request,
            "core/partials/day_journal_tile.html",
            {
                "selected_date": selected_date,
                "journal_entry": journal_entry,
                "saved": True,
            },
        )
        add_toast(response, "success", "Journal entry saved.")
        return response

    return render(
        request,
        "core/partials/day_journal_tile.html",
        {
            "selected_date": selected_date,
            "journal_entry": journal_entry,
        },
    )


def day_overview_mood(request: HttpRequest):
    date_str = request.GET.get("date") or request.POST.get("date")
    selected_date = _parse_date_param(date_str)
    mood_entries = _get_mood_entries(selected_date)

    if request.method == "POST":
        mood = request.POST.get("mood", "").strip()
        notes = request.POST.get("notes", "").strip()
        valid_moods = {value for value, _ in MoodChoices.choices}

        if mood not in valid_moods:
            response = render(
                request,
                "core/partials/day_mood_tile.html",
                {
                    "selected_date": selected_date,
                    "mood_entries": mood_entries,
                    "mood_choices": MoodChoices.choices,
                    "error": "Please select a valid mood.",
                },
            )
            return response

        MoodEntry.objects.create(mood=mood, notes=notes)
        mood_entries = _get_mood_entries(selected_date)

        response = render(
            request,
            "core/partials/day_mood_tile.html",
            {
                "selected_date": selected_date,
                "mood_entries": mood_entries,
                "mood_choices": MoodChoices.choices,
                "saved": True,
            },
        )
        add_toast(response, "success", "Mood logged.")
        return response

    return render(
        request,
        "core/partials/day_mood_tile.html",
        {
            "selected_date": selected_date,
            "mood_entries": mood_entries,
            "mood_choices": MoodChoices.choices,
        },
    )


def _parse_date_param(date_str: str | None) -> date:
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass
    return timezone.localdate()


def _get_open_tasks():
    return (
        Task.objects.filter(
            status__in=[TaskStatus.ON_DECK, TaskStatus.IN_PROGRESS, TaskStatus.TODO]
        )
        .select_related("project")
        .prefetch_related("tags")
        .order_by("status", "-priority", "due_at")
    )


def _get_journal_entry(selected_date: date) -> JournalEntry | None:
    return JournalEntry.objects.filter(date=selected_date).first()


def _get_mood_entries(selected_date: date):
    return MoodEntry.objects.filter(datetime__date=selected_date).order_by("-datetime")


@require_POST
def update_last_geolocation(request: HttpRequest):
    latitude = request.POST.get("latitude")
    longitude = request.POST.get("longitude")
    if latitude is None or longitude is None:
        return HttpResponse("Missing latitude or longitude", status=400)

    LastGeolocation.objects.update_or_create(
        pk=1,
        defaults={
            "latitude": latitude,
            "longitude": longitude,
        },
    )

    return HttpResponse(status=204)
