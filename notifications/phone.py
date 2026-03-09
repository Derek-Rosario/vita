from django.conf import settings
from twilio.rest import Client


def send_test_phone_call(
    *,
    to_phone_number: str | None = None,
    from_phone_number: str | None = None,
    twiml: str = "<Response><Say>Ahoy, World</Say></Response>",
) -> str:
    """Send a test phone call via Twilio and return the call SID."""
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    call = client.calls.create(
        twiml=twiml,
        to=to_phone_number or settings.TO_PHONE_NUMBER,
        from_=from_phone_number or settings.FROM_PHONE_NUMBER,
    )
    return call.sid
