from django.db import models
from django.utils import timezone
from datetime import timedelta


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the record was created.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When the record was last updated.",
    )

    class Meta:
        abstract = True


class LastGeolocation(TimestampedModel):
    latitude = models.FloatField(
        help_text="The last known latitude of the user.",
    )
    longitude = models.FloatField(
        help_text="The last known longitude of the user.",
    )

    @property
    def is_fresh(self) -> bool:
        """Determine if the geolocation data is fresh (updated within the last hour)."""

        return self.updated_at >= timezone.now() - timedelta(hours=1)

    def __str__(self):
        return f"Lat: {self.latitude}, Lon: {self.longitude} (as of {self.updated_at})"
