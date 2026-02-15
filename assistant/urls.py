from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat, name="assistant_chat"),
    path("messages/send/", views.send_message, name="assistant_send_message"),
    path("messages/clear/", views.clear_chat, name="assistant_clear_chat"),
]
