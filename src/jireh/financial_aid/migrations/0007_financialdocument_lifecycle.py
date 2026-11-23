"""Durable document metadata and PostgreSQL tenant/immutability guards.

No file bytes live in the database. No production upload routes are enabled.
"""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


SQL = """
CREATE FUNCTION jireh_document_scope_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Document metadata cannot be physically deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (
            NEW.school_id, NEW.household_id, NEW.application_id,
            NEW.created_by_id, NEW.object_key, NEW.request_key,
            NEW.version, NEW.category, NEW.detected_media_type,
            NEW.byte_count, NEW.sha256
        ) IS DISTINCT FROM (
            OLD.school_id, OLD.household_id, OLD.application_id,
            OLD.created_by_id, OLD.object_key, OLD.request_key,
            OLD.version, OLD.category, OLD.detected_media_type,
            OLD.byte_count, OLD.sha256
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Document identity and evidence are immutable';
        END IF;
        IF NOT (
            (OLD.state='ACTIVE' AND NEW.state='DELETE_PENDING'
                AND NEW.deleted_at IS NULL)
            OR (OLD.state='DELETE_PENDING' AND NEW.state='DELETED'
                AND NEW.deleted_at IS NOT NULL)
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Unapproved document lifecycle transition';
        END IF;
    ELSE
        IF NEW.state <> 'ACTIVE' OR NEW.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='New document must start active';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM financial_aid_aidapplication a
        JOIN schools_household h ON h.id=a.household_id
        JOIN schools_academicyear y ON y.id=a.academic_year_id
        JOIN schools_school s ON s.id=a.school_id
        WHERE a.id=NEW.application_id
          AND a.status='DRAFT'
          AND a.school_id=NEW.school_id
          AND h.id=NEW.household_id
          AND h.school_id=NEW.school_id
          AND y.school_id=NEW.school_id
          AND s.is_active
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Document application tenant mismatch';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE FUNCTION jireh_document_event_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Document lifecycle event is append-only';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM financial_aid_financialdocument d
        WHERE d.id=NEW.document_id AND d.school_id=NEW.school_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Document event tenant mismatch';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE TRIGGER jireh_document_metadata_guard
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_financialdocument
FOR EACH ROW EXECUTE FUNCTION jireh_document_scope_guard();

CREATE TRIGGER jireh_document_event_guard
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_financialdocumentevent
FOR EACH ROW EXECUTE FUNCTION jireh_document_event_guard();
"""
DROP = """
DROP TRIGGER IF EXISTS jireh_document_event_guard
ON financial_aid_financialdocumentevent;
DROP TRIGGER IF EXISTS jireh_document_metadata_guard
ON financial_aid_financialdocument;
DROP FUNCTION IF EXISTS jireh_document_event_guard();
DROP FUNCTION IF EXISTS jireh_document_scope_guard();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(SQL)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0006_syntheticaidoffer"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="FinancialDocument",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("object_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("request_key", models.UUIDField(editable=False, unique=True)),
                ("version", models.PositiveIntegerField()),
                ("category", models.CharField(max_length=48)),
                ("detected_media_type", models.CharField(max_length=96)),
                ("byte_count", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("state", models.CharField(max_length=16, default="ACTIVE", choices=[
                    ("ACTIVE", "Scanned"), ("DELETE_PENDING", "Pending secure removal"), ("DELETED", "Removed"),
                ])),
                ("deleted_at", models.DateTimeField(null=True, blank=True)),
                ("application", models.ForeignKey(
                    to="financial_aid.aidapplication", on_delete=django.db.models.deletion.PROTECT,
                    related_name="document_records",
                )),
                ("created_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                )),
                ("household", models.ForeignKey(
                    to="schools.household", on_delete=django.db.models.deletion.PROTECT,
                )),
                ("school", models.ForeignKey(
                    to="schools.school", on_delete=django.db.models.deletion.PROTECT,
                )),
            ],
        ),
        migrations.CreateModel(
            name="FinancialDocumentEvent",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("action", models.CharField(max_length=16, choices=[
                    ("CREATED", "Created"), ("DELETED", "Deleted"),
                ])),
                ("actor_user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                )),
                ("document", models.ForeignKey(
                    to="financial_aid.financialdocument",
                    related_name="events",
                    on_delete=django.db.models.deletion.PROTECT,
                )),
                ("school", models.ForeignKey(
                    to="schools.school", on_delete=django.db.models.deletion.PROTECT,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="financialdocument",
            constraint=models.UniqueConstraint(
                fields=["application", "version"], name="jireh_document_app_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="financialdocument",
            constraint=models.CheckConstraint(
                condition=Q(byte_count__gt=0), name="jireh_document_positive_bytes",
            ),
        ),
        migrations.AddConstraint(
            model_name="financialdocument",
            constraint=models.CheckConstraint(
                condition=Q(version__gt=0), name="jireh_document_positive_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="financialdocumentevent",
            constraint=models.UniqueConstraint(
                fields=["document", "action"], name="jireh_document_once_per_event",
            ),
        ),
        migrations.RunPython(install, remove),
    ]
