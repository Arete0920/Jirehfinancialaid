"""Two-operator first-director bootstrap evidence, internal-only.

No routes or runtime enablement. A partial unique constraint prevents
competing pending requests for the same school.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q
import django.db.models.deletion


PROTECT_SQL = """
CREATE FUNCTION jireh_first_director_request_protect() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Initial director approval evidence cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.school_id, NEW.subject_id, NEW.proposed_by_id,
               NEW.authorization_reference, NEW.expires_at, NEW.created_at)
          IS DISTINCT FROM
           ROW(OLD.school_id, OLD.subject_id, OLD.proposed_by_id,
               OLD.authorization_reference, OLD.expires_at, OLD.created_at)
           OR OLD.approved_at IS NOT NULL OR OLD.closed_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Initial director approval history is immutable';
        END IF;
        IF NOT (
            (NEW.closed_at IS NOT NULL AND NEW.approved_at IS NULL
             AND NEW.approved_by_id IS NULL AND NEW.grant_id IS NULL)
            OR
            (NEW.approved_at IS NOT NULL AND NEW.closed_at IS NULL
             AND NEW.approved_by_id IS NOT NULL AND NEW.grant_id IS NOT NULL)
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Invalid first director request transition';
        END IF;
        IF NEW.approved_at IS NOT NULL AND
           NOT EXISTS (
               SELECT 1 FROM schools_schoolstaffaccess
               WHERE id = NEW.grant_id AND school_id = NEW.school_id
                 AND user_id = NEW.subject_id AND is_active = TRUE
                 AND role = 'AID_DIRECTOR'
           ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'First director approval must match its grant';
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
        cursor.execute(PROTECT_SQL)
        cursor.execute(
            "CREATE TRIGGER jireh_first_director_request_protect_trigger "
            "BEFORE UPDATE OR DELETE ON schools_firstdirectorbootstraprequest "
            "FOR EACH ROW EXECUTE FUNCTION jireh_first_director_request_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_first_director_request_protect_trigger "
            "ON schools_firstdirectorbootstraprequest"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_first_director_request_protect()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0013_staff_grant_decision_creation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FirstDirectorBootstrapRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorization_reference", models.CharField(max_length=120)),
                ("expires_at", models.DateTimeField()),
                ("approved_at", models.DateTimeField(null=True, blank=True)),
                ("closed_at", models.DateTimeField(null=True, blank=True)),
                ("school", models.ForeignKey(
                    to="schools.school", on_delete=django.db.models.deletion.PROTECT,
                    related_name="first_director_bootstrap_requests",
                )),
                ("subject", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_first_director_requests",
                )),
                ("proposed_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_first_director_proposals",
                )),
                ("approved_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="jireh_first_director_approvals",
                )),
                ("grant", models.OneToOneField(
                    to="schools.schoolstaffaccess",
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="initial_director_approval",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["school"],
                        condition=Q(approved_at__isnull=True, closed_at__isnull=True),
                        name="jireh_one_pending_initial_director",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(approved_at__isnull=True, approved_by__isnull=True,
                              grant__isnull=True)
                            | Q(approved_at__isnull=False,
                                approved_by__isnull=False,
                                grant__isnull=False, closed_at__isnull=True)
                        ),
                        name="jireh_initial_director_state_valid",
                    ),
                    models.CheckConstraint(
                        condition=(Q(approved_by__isnull=True)
                                   | ~Q(proposed_by=F("approved_by"))),
                        name="jireh_initial_director_dual_control",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
