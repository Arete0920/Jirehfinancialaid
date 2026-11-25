"""Expand internal action evidence choices; no school creation or activation."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0024_school_preparation_event"),
    ]
    operations = [
        migrations.AlterField(
            model_name="operatorwebauthnactionintent",
            name="action",
            field=models.CharField(max_length=24, choices=[
                ("DIRECTOR_PROPOSE", "Director proposal"),
                ("DIRECTOR_APPROVE", "Director approval"),
                ("SCHOOL_SETUP_PROPOSE", "School setup proposal"),
                ("SCHOOL_SETUP_APPROVE", "School setup approval"),
            ]),
        ),
    ]
