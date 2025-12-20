from django.urls import path
from . import views

urlpatterns = [
    path("vapid-public-key/", views.vapid_public_key, name="vapid_public_key"),
    path("subscribe/", views.subscribe, name="webpush_subscribe"),
    path("send-test/", views.send_test, name="webpush_send_test"),
]
