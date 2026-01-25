from django.db import models
from core.models import TimestampedModel


class MoodChoices(models.TextChoices):
    HAPPY = "happy", "Happy"
    SAD = "sad", "Sad"
    BORED = "bored", "Bored"
    NEUTRAL = "neutral", "Neutral"
    EXCITED = "excited", "Excited"
    ANGRY = "angry", "Angry"
    ANXIOUS = "anxious", "Anxious"
    RELAXED = "relaxed", "Relaxed"
    TIRED = "tired", "Tired"
    CONFUSED = "confused", "Confused"
    GRATEFUL = "grateful", "Grateful"
    FRUSTRATED = "frustrated", "Frustrated"


class MoodEntry(TimestampedModel):
    datetime = models.DateTimeField(auto_now_add=True)
    mood = models.CharField(max_length=10, choices=MoodChoices.choices)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.datetime}: {self.mood}"


class JournalEntry(TimestampedModel):
    title = models.CharField(max_length=200)
    date = models.DateField()
    content_markdown = models.TextField()

    def __str__(self):
        return f"{self.date} - {self.title}"


class DreamTypeChoices(models.TextChoices):
    NIGHTMARE = "nightmare", "Nightmare"
    NEUTRAL = "neutral", "Neutral"
    HAPPY = "happy", "Happy"


class DreamEntry(TimestampedModel):
    date = models.DateField(auto_now_add=True)
    type = models.CharField(max_length=10, choices=DreamTypeChoices.choices)
    content_markdown = models.TextField()

    def __str__(self):
        return f"{self.date} - {self.get_type_display()} Dream"
