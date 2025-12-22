from django.urls import path

from social import views

app_name = "social"

urlpatterns = [
    path("", views.index, name="index"),
    path("contacts/quick_add/", views.quick_add_contact, name="quick_add_contact"),
]
