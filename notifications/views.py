import json
import logging
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .models import WebPushSubscription
from .services import send_webpush

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def vapid_public_key(request: HttpRequest) -> JsonResponse:
    key = getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", None)
    return JsonResponse({"publicKey": key})


@require_http_methods(["POST"])
def subscribe(request: HttpRequest) -> JsonResponse:
    data = json.loads(request.body.decode("utf-8"))
    endpoint = data.get("endpoint")
    keys = data.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return JsonResponse({"ok": False, "error": "invalid subscription"}, status=400)

    # Upsert by endpoint
    sub, _created = WebPushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user if request.user.is_authenticated else None,
            "p256dh": p256dh,
            "auth": auth,
            "active": True,
        },
    )
    return JsonResponse({"ok": True})


@require_http_methods(["POST"])  # simple manual trigger to test
def send_test(request: HttpRequest) -> JsonResponse:
    payload = {
        "title": "Vita",
        "body": "Test notification",
        "url": "/",
    }
    subs = WebPushSubscription.objects.filter(active=True)
    sent = 0
    for sub in subs:
        try:
            send_webpush(sub, payload)
            sent += 1
        except Exception:
            logger.error("Failed to send webpush to %s", sub.endpoint, exc_info=True)
            sub.active = False
            sub.save(update_fields=["active"])
    return JsonResponse({"ok": True, "sent": sent})
