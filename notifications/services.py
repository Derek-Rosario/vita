import json

from django.conf import settings
from pywebpush import WebPushException, webpush


def send_webpush(subscription, payload: dict):
    """Send a web push notification to a subscription using VAPID keys."""
    vapid_private = getattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", None)
    vapid_email = getattr(settings, "WEBPUSH_VAPID_EMAIL", None)

    if not vapid_private or not vapid_email:
        raise RuntimeError("Missing WEBPUSH_VAPID_PRIVATE_KEY or WEBPUSH_VAPID_EMAIL settings")

    return webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.p256dh,
                "auth": subscription.auth,
            },
        },
        data=json.dumps(payload),
        vapid_private_key=vapid_private,
        vapid_claims={"sub": f"mailto:{vapid_email}"},
    )
