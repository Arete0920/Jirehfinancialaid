"""Allow audited creation decisions for additional verified school directors."""

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("schools", "0012_recovery_contact_rotation")]

    operations = [
        migrations.RemoveConstraint(
            model_name="schoolgrantdecisionevent",
            name="jireh_operator_revoke_only",
        ),
        migrations.AlterField(
            model_name="schoolgrantdecisionevent",
            name="action",
            field=models.CharField(
                max_length=16,
                choices=[("CREATED", "Created"), ("REVOKED", "Revoked")],
            ),
        ),
        migrations.AddConstraint(
            model_name="schoolgrantdecisionevent",
            constraint=models.CheckConstraint(
                condition=Q(action__in=["CREATED", "REVOKED"]),
                name="jireh_operator_action_valid",
            ),
        ),
    ]
