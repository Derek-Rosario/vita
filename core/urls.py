from django.urls import path

from . import views

urlpatterns = [
    path(
        "update-geolocation/", views.update_last_geolocation, name="update_geolocation"
    ),
    path("day/", views.day_overview, name="day_overview"),
    path(
        "day/tasks/<int:task_id>/done/",
        views.day_overview_mark_task_done,
        name="day_overview_mark_task_done",
    ),
    path("day/journal/", views.day_overview_journal, name="day_overview_journal"),
    path("day/mood/", views.day_overview_mood, name="day_overview_mood"),
]
