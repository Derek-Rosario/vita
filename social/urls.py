from django.urls import path

from social import views

app_name = "social"

urlpatterns = [
    path("", views.index, name="index"),
    path("contacts", views.list_contacts, name="list_contacts"),
    path("contacts/quick_add/", views.quick_add_contact, name="quick_add_contact"),
    path(
        "contacts/log_touchpoint/<str:contact_pk>/",
        views.log_contact_touchpoint_modal,
        name="log_contact_touchpoint_modal",
    ),
]
