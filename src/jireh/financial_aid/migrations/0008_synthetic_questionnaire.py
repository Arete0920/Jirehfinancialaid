"""Disposable questionnaire snapshot and metadata-only revision evidence."""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


SQL = """
CREATE FUNCTION jireh_syn_questionnaire_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.application_id IS DISTINCT FROM OLD.application_id
           OR NEW.id IS DISTINCT FROM OLD.id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Invalid questionnaire revision transition';
        END IF;
    ELSIF NEW.revision <> 1 THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Questionnaire must start at revision one';
    END IF;
    IF octet_length(NEW.ciphertext) NOT BETWEEN 29 AND 32796
       OR NOT EXISTS (
        SELECT 1 FROM financial_aid_aidapplication a
        JOIN schools_household h ON h.id=a.household_id
        JOIN schools_academicyear y ON y.id=a.academic_year_id
        JOIN schools_school s ON s.id=a.school_id
        WHERE a.id=NEW.application_id AND a.status='DRAFT'
          AND h.school_id=a.school_id AND y.school_id=a.school_id
          AND h.is_active AND s.is_active
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Invalid questionnaire snapshot';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE FUNCTION jireh_syn_questionnaire_event_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Questionnaire revision evidence is immutable';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM financial_aid_syntheticquestionnairedraft q
        JOIN financial_aid_aidapplication a ON a.id=q.application_id
        JOIN schools_householdaccess g ON g.household_id=a.household_id
        WHERE q.id=NEW.questionnaire_id AND q.revision=NEW.revision
          AND g.user_id=NEW.actor_user_id AND g.is_active
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Invalid questionnaire revision evidence';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;

CREATE TRIGGER jireh_syn_questionnaire_guard
BEFORE INSERT OR UPDATE ON financial_aid_syntheticquestionnairedraft
FOR EACH ROW EXECUTE FUNCTION jireh_syn_questionnaire_guard();
CREATE TRIGGER jireh_syn_questionnaire_event_guard
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_syntheticquestionnaireevent
FOR EACH ROW EXECUTE FUNCTION jireh_syn_questionnaire_event_guard();
"""
DROP = """
DROP TRIGGER IF EXISTS jireh_syn_questionnaire_event_guard
ON financial_aid_syntheticquestionnaireevent;
DROP TRIGGER IF EXISTS jireh_syn_questionnaire_guard
ON financial_aid_syntheticquestionnairedraft;
DROP FUNCTION IF EXISTS jireh_syn_questionnaire_event_guard();
DROP FUNCTION IF EXISTS jireh_syn_questionnaire_guard();
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
        ("financial_aid", "0007_financialdocument_lifecycle"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SyntheticQuestionnaireDraft",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                        editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revision", models.PositiveIntegerField()),
                ("ciphertext", models.BinaryField(max_length=32796, editable=False)),
                ("application", models.OneToOneField(
                    to="financial_aid.aidapplication",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_questionnaire",
                )),
            ],
        ),
        migrations.CreateModel(
            name="SyntheticQuestionnaireEvent",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                        editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revision", models.PositiveIntegerField()),
                ("actor_user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                )),
                ("questionnaire", models.ForeignKey(
                    to="financial_aid.syntheticquestionnairedraft",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="events",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="syntheticquestionnairedraft",
            constraint=models.CheckConstraint(
                condition=Q(revision__gt=0), name="jireh_syn_questionnaire_revision_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticquestionnaireevent",
            constraint=models.UniqueConstraint(
                fields=["questionnaire", "revision"], name="jireh_syn_questionnaire_event_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticquestionnaireevent",
            constraint=models.CheckConstraint(
                condition=Q(revision__gt=0), name="jireh_syn_questionnaire_event_positive",
            ),
        ),
        migrations.RunPython(install, remove),
    ]
