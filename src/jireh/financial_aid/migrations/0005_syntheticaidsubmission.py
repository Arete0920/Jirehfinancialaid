"""Disposable synthetic consent receipt with PostgreSQL raw-write guards.

Records only an explicitly fictional presentation milestone. The real
AidApplication.status remains DRAFT. The PostgreSQL guards are not RLS and do
not authorize live data intake; DB administrators can still bypass triggers.
"""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


INSTALL = """
CREATE FUNCTION jireh_synthetic_receipt_integrity() RETURNS trigger AS $body$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Synthetic receipt is immutable';
    END IF;
    IF NEW.accuracy_attested IS DISTINCT FROM TRUE
       OR NEW.consent_version IS DISTINCT FROM 'synthetic-demo-v1' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Synthetic consent evidence invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM financial_aid_aidapplication a
          JOIN schools_household h ON h.id = a.household_id
          JOIN schools_academicyear y ON y.id = a.academic_year_id
          JOIN schools_school school ON school.id = a.school_id
          JOIN schools_householdaccess access
            ON access.household_id = a.household_id
           AND access.user_id = NEW.actor_user_id AND access.is_active
          JOIN financial_aid_aidapplicationstudent sel ON sel.application_id = a.id
          JOIN schools_householdstudent hs
            ON hs.id = sel.household_student_id AND hs.household_id = a.household_id
         WHERE a.id = NEW.application_id
           AND a.status = 'DRAFT'
           AND h.school_id = a.school_id AND h.is_active
           AND y.school_id = a.school_id AND school.is_active
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Synthetic receipt school, grant or child mismatch';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE FUNCTION jireh_synthetic_selection_integrity() RETURNS trigger AS $body$
DECLARE
    related_app uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        related_app := OLD.application_id;
    ELSE
        related_app := NEW.application_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM financial_aid_syntheticaidsubmission
         WHERE application_id = related_app
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Synthetic receipt locks selected children';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE TRIGGER jireh_synthetic_receipt_freeze
BEFORE INSERT OR UPDATE OR DELETE
ON financial_aid_syntheticaidsubmission
FOR EACH ROW EXECUTE FUNCTION jireh_synthetic_receipt_integrity();

CREATE TRIGGER jireh_synthetic_selection_freeze
BEFORE INSERT OR UPDATE OR DELETE
ON financial_aid_aidapplicationstudent
FOR EACH ROW EXECUTE FUNCTION jireh_synthetic_selection_integrity();
"""

REMOVE = """
DROP TRIGGER IF EXISTS jireh_synthetic_selection_freeze
ON financial_aid_aidapplicationstudent;
DROP TRIGGER IF EXISTS jireh_synthetic_receipt_freeze
ON financial_aid_syntheticaidsubmission;
DROP FUNCTION IF EXISTS jireh_synthetic_selection_integrity();
DROP FUNCTION IF EXISTS jireh_synthetic_receipt_integrity();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(INSTALL)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(REMOVE)


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0004_pg_tenant_triggers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SyntheticAidSubmission",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("consent_version", models.CharField(max_length=64)),
                ("accuracy_attested", models.BooleanField(default=False)),
                ("application", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_submission",
                    to="financial_aid.aidapplication",
                )),
                ("actor_user", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_synthetic_submissions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="syntheticaidsubmission",
            constraint=models.CheckConstraint(
                condition=Q(accuracy_attested=True),
                name="jireh_synthetic_attested_true",
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticaidsubmission",
            constraint=models.CheckConstraint(
                condition=Q(consent_version="synthetic-demo-v1"),
                name="jireh_synthetic_disclosure_v1",
            ),
        ),
        migrations.RunPython(install, remove),
    ]
