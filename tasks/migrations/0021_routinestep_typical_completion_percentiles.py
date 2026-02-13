from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0020_scheduledawaytrip_delete_isawayfromhome"),
    ]

    operations = [
        migrations.AddField(
            model_name="routinestep",
            name="typical_completion_time_p25",
            field=models.TimeField(
                blank=True,
                help_text="25th percentile of completion time-of-day for completed tasks from this step.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="routinestep",
            name="typical_completion_time_p75",
            field=models.TimeField(
                blank=True,
                help_text="75th percentile of completion time-of-day for completed tasks from this step.",
                null=True,
            ),
        ),
    ]
