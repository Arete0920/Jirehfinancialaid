"""Test-only persistent authentication throttle; no usernames or secrets stored."""

import uuid

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0009_redemption_attempt_budget"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginAttemptBudget",
            fields=[
                ("id", models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("identifier_digest", models.CharField(
                    max_length=64, unique=True,
                )),
                ("window_started_at", models.DateTimeField()),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(attempt_count__lte=10),
                        name="jireh_login_attempt_max10",
                    ),
                ],
            },
        ),
    ]
