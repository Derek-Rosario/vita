import json
from typing import Literal
from django.http import HttpResponse

from core.constants import HOME_COORDINATES


def add_htmx_trigger(
    response: HttpResponse,
    trigger_name: str,
    trigger_data: dict = {},
):
    """Add or edit HX-Trigger header to include custom trigger data."""
    existing_triggers = {}
    if response.has_header("HX-Trigger"):
        existing_triggers = json.loads(response["HX-Trigger"])
    existing_triggers[trigger_name] = trigger_data
    response["HX-Trigger"] = json.dumps(existing_triggers)


def add_toast(
    response: HttpResponse,
    type: Literal["success"] | Literal["error"] | Literal["info"],
    message: str,
):
    """Add a toast message to an HttpResponse using HTMX triggers. Optionally add a custom voice message."""
    add_htmx_trigger(
        response,
        "toastMessage",
        {"type": type, "message": message},
    )


def add_voice_message(
    response: HttpResponse,
    message: str,
):
    add_htmx_trigger(response, "speak", {"message": message})


def is_close_to_home(latitude: float, longitude: float) -> bool:
    """Determine if the given latitude and longitude are close to home location."""

    THRESHOLD = 0.01  # Approx ~1km

    lat_diff = abs(latitude - HOME_COORDINATES["latitude"])
    lon_diff = abs(longitude - HOME_COORDINATES["longitude"])

    return lat_diff <= THRESHOLD and lon_diff <= THRESHOLD
