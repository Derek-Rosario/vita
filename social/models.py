import datetime
from django.db import models
from core.models import TimestampedModel
from django.core.validators import MaxValueValidator
from django.utils.text import slugify
from django.utils.timezone import now as django_now


class RelationshipType(models.TextChoices):
    PARTNER = "partner", "Partner"
    SIBLING = "sibling", "Sibling"
    CHILD = "child", "Child"
    PARENT = "parent", "Parent"
    FAMILY = "family", "Family"
    FRIEND = "friend", "Friend"
    COLLEAGUE = "colleague", "Colleague"
    ACQUAINTANCE = "acquaintance", "Acquaintance"
    OTHER = "other", "Other"


class TouchpointChannel(models.TextChoices):
    PHONE = "phone", "Phone"
    EMAIL = "email", "Email"
    IN_PERSON = "in_person", "In Person"
    VIDEO_CALL = "video_call", "Video Call"
    TEXT_MESSAGE = "text_message", "Text Message"
    SOCIAL_MEDIA = "social_media", "Social Media"
    OTHER = "other", "Other"


class Contact(TimestampedModel):
    slug = models.SlugField(unique=True, primary_key=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100, blank=True)
    priority = models.PositiveSmallIntegerField(
        default=1, validators=[MaxValueValidator(10)]
    )
    relationship_to_me = models.CharField(
        max_length=20, choices=RelationshipType.choices
    )
    birthday = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    interests = models.ManyToManyField("Interest", blank=True, related_name="contacts")
    timezone = models.CharField(max_length=50, default="America/New_York")
    preferred_channel = models.CharField(
        max_length=100, choices=TouchpointChannel.choices, blank=True
    )
    check_in_frequency_days = models.PositiveIntegerField(default=30)
    last_contacted_at = models.DateField(null=True, blank=True)
    strength = models.PositiveSmallIntegerField(default=0, db_index=True)

    @property
    def name(self):
        return self.nickname if self.nickname else f"{self.first_name} {self.last_name}"

    def create_contact_task(self):
        """
        Create a task/reminder to contact this person based on their check-in frequency.
        """
        from tasks.models import Task

        # Skip if existing non-done and non-cancelled task exists for this contact
        existing_tasks = Task.objects.filter(
            related_contact=self,
        ).exclude(
            status__in=[Task.Status.DONE, Task.Status.CANCELLED],
        )
        if existing_tasks.exists():
            return

        due_at = django_now().date() + datetime.timedelta(days=3)
        return Task.objects.create(
            title=f"Check in with {self.name}",
            estimate_minutes=30,
            energy=Task.Energy.HIGH,
            due_at=due_at,
            related_contact=self,
        )

    def update_strength(self):
        """
        Calculate and update the strength score (0-100) for this contact.
        100 = fully in compliance with desired contact frequency
        0 = not in compliance at all

        Priority affects decay rate:
        - Priority 1 (most important): fastest decay when off cadence
        - Priority 10 (least important): slowest decay when off cadence
        """
        if not self.last_contacted_at:
            self.strength = 0
            return

        days_since_contact = (django_now().date() - self.last_contacted_at).days

        # Within target frequency - full compliance
        if days_since_contact <= self.check_in_frequency_days:
            self.strength = 100
        else:
            # Overdue - calculate decay based on priority
            days_overdue = days_since_contact - self.check_in_frequency_days

            # Priority affects decay rate (1 = fastest, 10 = slowest)
            # Normalize priority to decay factor: 1.0 for priority 1, 0.1 for priority 10
            decay_rate = (11 - self.priority) / 10

            # Calculate decay as a function of how many check-in periods we're overdue
            decay_periods = days_overdue / self.check_in_frequency_days
            decay_amount = min(100, decay_periods * 100 * decay_rate)

            self.strength = max(0, int(100 - decay_amount))

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.update_strength()
        super(Contact, self).save(*args, **kwargs)


class ContactRelationship(TimestampedModel):
    from_contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    to_contact = models.ForeignKey(
        Contact, related_name="related_to", on_delete=models.CASCADE
    )
    relationship_type = models.CharField(
        max_length=20, choices=RelationshipType.choices
    )
    details = models.TextField(blank=True)

    def __str__(self):
        return f"{self.from_contact.name} <> {self.to_contact.name} ({self.relationship_type})"


class ContactTouchpoint(TimestampedModel):
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="touchpoints"
    )
    date = models.DateField()
    channel = models.CharField(max_length=100, choices=TouchpointChannel.choices)

    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Touchpoint with {self.contact.name} on {self.date}"

    # Update contact's last_contacted_at on save
    def save(self, *args, **kwargs):
        super(ContactTouchpoint, self).save(*args, **kwargs)

        # Refresh contact from database to avoid stale data
        self.contact.refresh_from_db()

        # Update last_contacted_at if this touchpoint is newer
        if (
            not self.contact.last_contacted_at
            or self.date > self.contact.last_contacted_at
        ):
            self.contact.last_contacted_at = self.date

        # Update contact strength and save
        self.contact.save()


class Interest(TimestampedModel):
    slug = models.SlugField(unique=True, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super(Interest, self).save(*args, **kwargs)


class Group(TimestampedModel):
    slug = models.SlugField(unique=True, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(Contact, related_name="groups", blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super(Group, self).save(*args, **kwargs)
