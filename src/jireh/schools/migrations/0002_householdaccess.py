"""Add authenticated household grants without granting access via shared students."""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HouseholdAccess",
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
                ("is_active", models.BooleanField(default=True)),
                (
                    "household",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_grants",
                        to="schools.household",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jireh_household_access",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("household", "user"),
                        name="jireh_household_access_unique",
                    )
                ],
            },
        ),
    ]
