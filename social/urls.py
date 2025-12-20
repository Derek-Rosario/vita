from django.urls import path

from social import views

urlpatterns = [
    path("contacts/", views.list_contacts, name="social_contacts"),
]
