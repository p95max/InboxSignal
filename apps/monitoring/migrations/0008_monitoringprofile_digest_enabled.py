# Generated manually for digest notification opt-in flag.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0007_monitoringprofile_digest_interval_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringprofile",
            name="digest_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Enable grouped digest notifications for this profile.",
            ),
        ),
    ]
