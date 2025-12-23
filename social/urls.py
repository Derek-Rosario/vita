from django.urls import path

from social import views

app_name = "social"

urlpatterns = [
    path("", views.index, name="index"),
    path("contacts", views.list_contacts, name="list_contacts"),
    path("contacts/quick_add/", views.quick_add_contact, name="quick_add_contact"),
    path(
        "contacts/<str:contact_pk>/touchpoints/",
        views.log_contact_touchpoint_modal,
        name="log_contact_touchpoint_modal",
    ),
    path(
        "contacts/<str:contact_pk>/task/",
        views.create_contact_task,
        name="create_contact_task",
    ),
]
