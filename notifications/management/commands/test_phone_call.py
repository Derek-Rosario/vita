from xml.sax.saxutils import escape
from twilio.twiml.voice_response import Pause, VoiceResponse, Say

from django.core.management.base import BaseCommand, CommandError, CommandParser

from notifications.phone import send_test_phone_call


class Command(BaseCommand):
    help = "Send a test Twilio phone call."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--to",
            dest="to_phone_number",
            type=str,
            help="Destination phone number. Defaults to settings.TO_PHONE_NUMBER.",
        )
        parser.add_argument(
            "--from",
            dest="from_phone_number",
            type=str,
            help="Caller phone number. Defaults to settings.FROM_PHONE_NUMBER.",
        )
        parser.add_argument(
            "--message",
            type=str,
            default="Ahoy, World",
            help="Text spoken in the test call.",
        )

    def handle(self, *args, **options) -> None:
        message = options["message"]

        response = VoiceResponse()
        response.pause(length=5)
        response.say(message)

        try:
            sid = send_test_phone_call(
                to_phone_number=options.get("to_phone_number"),
                from_phone_number=options.get("from_phone_number"),
                twiml=response.to_xml(),
            )
        except Exception as exc:
            raise CommandEor(f"Failed to send test phone call: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Test phone call queued with SID: {sid}"))
