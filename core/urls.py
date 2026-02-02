from django.urls import path

from . import views

urlpatterns = [
    path(
        "update-geolocation/", views.update_last_geolocation, name="update_geolocation"
    ),
]
