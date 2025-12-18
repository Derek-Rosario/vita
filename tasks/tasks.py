import logging
from django.tasks import task
from tasks.services import generate_tasks_for_date

logger = logging.getLogger(__name__)


@task()
def run_routines():
    """Run all active routines to generate tasks as needed."""
    created_tasks = generate_tasks_for_date()
    logger.info(f"Generated {len(created_tasks)} tasks from routines.")
    return [task.pk for task in created_tasks]
