from django.conf import settings
from django.db import models


class WebPushSubscription(models.Model):
	"""Stores a Web Push subscription for a user or anonymous device."""

	user = models.ForeignKey(
		settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
	)
	endpoint = models.URLField(unique=True)
	p256dh = models.CharField(max_length=255)
	auth = models.CharField(max_length=255)
	created_at = models.DateTimeField(auto_now_add=True)
	active = models.BooleanField(default=True)

	def __str__(self) -> str:
		owner = getattr(self.user, "username", "anon")
		return f"{owner} - {self.endpoint[:32]}..."
