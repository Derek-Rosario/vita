from django.urls import path

from assistant.constants import TWILIO_CONVERSATION_RELAY_WS_PATH
from assistant.consumers import ConversationRelayConsumer

websocket_urlpatterns = [
    path(
        TWILIO_CONVERSATION_RELAY_WS_PATH.lstrip("/"),
        ConversationRelayConsumer.as_asgi(),
    ),
]
