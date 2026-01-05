import logging
from django.tasks import task
from .models import Contact

logger = logging.getLogger(__name__)


@task()
def recalculate_contact_strengths():
    """Recalculate strength scores for all contacts."""
    contacts = Contact.objects.all()
    count = 0
    for contact in contacts:
        contact.save()
        count += 1
    logger.info(f"Recalculated strength scores for {count} contacts.")
    return count
