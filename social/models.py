from django.db import models
from core.models import TimestampedModel
from django.core.validators import MaxValueValidator


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
    name = models.CharField(max_length=100)
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


class ContactTouchpointSentiment(models.TextChoices):
    POSITIVE = "positive", "Positive"
    NEUTRAL = "neutral", "Neutral"
    NEGATIVE = "negative", "Negative"


class ContactTouchpoint(TimestampedModel):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
    date = models.DateField()
    channel = models.CharField(max_length=100, choices=TouchpointChannel.choices)
    sentiment = models.CharField(
        max_length=100, blank=True, choices=ContactTouchpointSentiment.choices
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Touchpoint with {self.contact.name} on {self.date}"


class Interest(TimestampedModel):
    slug = models.SlugField(unique=True, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Group(TimestampedModel):
    slug = models.SlugField(unique=True, primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(Contact, related_name="groups", blank=True)

    def __str__(self):
        return self.name
