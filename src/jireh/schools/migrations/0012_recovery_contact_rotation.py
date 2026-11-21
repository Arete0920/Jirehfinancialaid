"""Preserve recovery contact history and enforce append-only rotation evidence."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


GUARDS = """
CREATE FUNCTION jireh_recovery_rotation_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_TABLE_NAME = 'schools_verifiedrecoverycontact' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Recovery contacts cannot be deleted';
        END IF;
        IF TG_OP = 'INSERT' AND NEW.superseded_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'A new recovery contact must start current';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.superseded_at IS NOT NULL AND
           NEW.superseded_at IS DISTINCT FROM OLD.superseded_at THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'A superseded recovery contact cannot be restored';
        END IF;
    ELSIF TG_TABLE_NAME = 'schools_recoverycontactrotationevent' THEN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Recovery rotation events are append-only';
        END IF;
        IF NEW.old_contact_id = NEW.new_contact_id OR
           NEW.actor_id <> NEW.user_id OR
           NOT EXISTS (
               SELECT 1 FROM schools_verifiedrecoverycontact
               WHERE id = NEW.old_contact_id AND user_id = NEW.user_id
                 AND superseded_at IS NOT NULL
           ) OR
           NOT EXISTS (
               SELECT 1 FROM schools_verifiedrecoverycontact
               WHERE id = NEW.new_contact_id AND user_id = NEW.user_id
                 AND superseded_at IS NULL
           ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Recovery rotation event account or contact mismatch';
        END IF;
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(GUARDS)
        for table in (
            "schools_verifiedrecoverycontact",
            "schools_recoverycontactrotationevent",
        ):
            cursor.execute(
                "CREATE TRIGGER jireh_" + table + "_rotation_guard "
                "BEFORE INSERT OR UPDATE OR DELETE ON " + table
                + " FOR EACH ROW EXECUTE FUNCTION jireh_recovery_rotation_guard()"
            )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in (
            "schools_verifiedrecoverycontact",
            "schools_recoverycontactrotationevent",
        ):
            cursor.execute(
                "DROP TRIGGER IF EXISTS jireh_" + table + "_rotation_guard ON " + table
            )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_recovery_rotation_guard()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0011_verified_password_recovery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="verifiedrecoverycontact",
            name="user",
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jireh_recovery_contacts",
            ),
        ),
        migrations.AddField(
            model_name="verifiedrecoverycontact",
            name="superseded_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="verifiedrecoverycontact",
            constraint=models.UniqueConstraint(
                fields=["user"],
                condition=Q(superseded_at__isnull=True),
                name="jireh_one_current_recovery_contact",
            ),
        ),
        migrations.CreateModel(
            name="RecoveryContactRotationEvent",
            fields=[
                ("id", models.UUIDField(
                    primary_key=True, default=uuid.uuid4,
                    editable=False, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_recovery_contact_rotations",
                )),
                ("actor", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_recovery_rotations_performed",
                )),
                ("old_contact", models.OneToOneField(
                    to="schools.verifiedrecoverycontact",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="rotation_out",
                )),
                ("new_contact", models.OneToOneField(
                    to="schools.verifiedrecoverycontact",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="rotation_in",
                )),
            ],
        ),
        migrations.RunPython(install, remove),
    ]
