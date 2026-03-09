"""
ASGI config for vita project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import path, re_path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vita.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from core.sse import SSEConsumer  # noqa: E402 - must import after Django setup
from assistant.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": URLRouter(
            [
                path("events/", SSEConsumer.as_asgi()),
                re_path(r"", django_asgi_app),
            ]
        ),
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
