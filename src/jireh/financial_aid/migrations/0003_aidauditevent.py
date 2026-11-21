"""Audit creation and first-time student selection in standalone Jireh."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0002_aidapplicationstudent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AidAuditEvent",
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
                    "action",
                    models.CharField(
                        max_length=32,
                        choices=[
                            ("DRAFT_CREATED", "Household draft created"),
                            ("STUDENT_SELECTED", "Student selected in draft"),
                        ],
                    ),
                ),
                (
                    "actor_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jireh_aid_events_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to="financial_aid.aidapplication",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jireh_aid_audit_events",
                        to="schools.school",
                    ),
                ),
                (
                    "student_selection",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to="financial_aid.aidapplicationstudent",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            Q(action="DRAFT_CREATED", student_selection__isnull=True)
                            | Q(action="STUDENT_SELECTED", student_selection__isnull=False)
                        ),
                        name="jireh_aid_event_action_selection",
                    ),
                    models.UniqueConstraint(
                        fields=("application",),
                        condition=Q(action="DRAFT_CREATED"),
                        name="jireh_one_draft_created_event",
                    ),
                    models.UniqueConstraint(
                        fields=("student_selection",),
                        condition=Q(action="STUDENT_SELECTED"),
                        name="jireh_one_student_selected_event",
                    ),
                ],
            },
        ),
    ]
