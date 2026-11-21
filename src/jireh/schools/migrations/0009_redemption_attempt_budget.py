"""Per-account, durable, bounded redemption attempt budget; no secrets stored."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0008_verified_invitation_redemption"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RedemptionAttemptBudget",
            fields=[
                ("id", models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("window_started_at", models.DateTimeField()),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_redemption_attempt_budget",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(attempt_count__lte=10),
                        name="jireh_redemption_attempt_max10",
                    )
                ],
            },
        ),
    ]
