import datetime
import json
import random
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from faker import Faker
from django.utils import timezone


RELATIONSHIPS = [
    "partner",
    "sibling",
    "child",
    "parent",
    "family",
    "friend",
    "colleague",
    "acquaintance",
    "other",
]

CHANNELS = [
    "phone",
    "email",
    "in_person",
    "video_call",
    "text_message",
    "social_media",
    "other",
]

TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Australia/Sydney",
]

FREQUENCIES = [7, 14, 21, 30, 45, 60, 90, 120, 180, 365]


class Command(BaseCommand):
    help = "Generate a JSON fixture of social contacts using Faker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=100,
            help="Number of contacts to generate (default: 100)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="social/fixtures/contacts_faker.json",
            help="Output fixture path (default: social/fixtures/contacts_faker.json)",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for deterministic data (default: 42)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        output = Path(options["output"])
        seed = options["seed"]

        if count <= 0:
            raise CommandError("--count must be greater than 0")

        output.parent.mkdir(parents=True, exist_ok=True)

        faker = Faker()
        Faker.seed(seed)
        random.seed(seed)

        items = []
        touchpoint_items = []
        touchpoint_pk = 1
        for i in range(1, count + 1):
            first_name = faker.first_name()
            last_name = faker.last_name()
            nickname = "" if i % 5 == 0 else faker.first_name()
            slug = f"contact-{i:03d}"

            touchpoints_count = 0 if i % 3 == 0 else random.randint(1, 3)
            touchpoint_dates = []
            for _ in range(touchpoints_count):
                created_at = faker.date_time_between(
                    start_date="-1y",
                    end_date="now",
                    tzinfo=timezone.get_current_timezone(),
                )
                updated_at = created_at + datetime.timedelta(
                    minutes=random.randint(0, 1440)
                )
                date = created_at.date()
                touchpoint_dates.append(date)

                touchpoint_items.append(
                    {
                        "model": "social.contacttouchpoint",
                        "pk": touchpoint_pk,
                        "fields": {
                            "created_at": created_at.isoformat(),
                            "updated_at": updated_at.isoformat(),
                            "contact": slug,
                            "date": date.isoformat(),
                            "channel": random.choice(CHANNELS),
                            "notes": f"Fixture touchpoint for {slug}.",
                        },
                    }
                )
                touchpoint_pk += 1

            last_contacted_at = max(touchpoint_dates) if touchpoint_dates else None

            items.append(
                {
                    "model": "social.contact",
                    "pk": slug,
                    "fields": {
                        "created_at": faker.date_time_between(
                            start_date="-2y", end_date="now"
                        ).isoformat(),
                        "updated_at": timezone.now().isoformat(),
                        "first_name": first_name,
                        "last_name": last_name,
                        "nickname": nickname,
                        "priority": (i % 10) + 1,
                        "relationship_to_me": random.choice(RELATIONSHIPS),
                        "birthday": faker.date_of_birth(
                            minimum_age=18, maximum_age=70
                        ).isoformat(),
                        "notes": f"Fixture contact {i:03d}.",
                        "timezone": random.choice(TIMEZONES),
                        "preferred_channel": ""
                        if i % 8 == 0
                        else random.choice(CHANNELS),
                        "check_in_frequency_days": random.choice(FREQUENCIES),
                        "last_contacted_at": last_contacted_at.isoformat()
                        if last_contacted_at
                        else None,
                        "strength": random.randint(0, 100),
                        "is_ever_contacted": bool(touchpoint_dates),
                    },
                }
            )

        output.write_text(
            json.dumps(items + touchpoint_items, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {count} contacts fixture at {output.as_posix()}"
            )
        )
