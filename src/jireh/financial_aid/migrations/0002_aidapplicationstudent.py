"""Add a school- and household-checked child selection to annual drafts."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0001_initial"),
        ("schools", "0003_schoolstaffaccess"),
    ]

    operations = [
        migrations.CreateModel(
            name="AidApplicationStudent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="student_selections",
                        to="financial_aid.aidapplication",
                    ),
                ),
                (
                    "household_student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="aid_selections",
                        to="schools.householdstudent",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("application", "household_student"),
                        name="jireh_aid_application_student_unique",
                    )
                ]
            },
        )
    ]
