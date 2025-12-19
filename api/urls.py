from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from .views import tasks

urlpatterns = [
    path("tasks/", tasks.list_tasks),
]
