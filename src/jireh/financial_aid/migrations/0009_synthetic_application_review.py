"""Metadata-only rehearsal confirmation, not legal consent or submission."""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


SQL = """
CREATE FUNCTION jireh_syn_review_guard() RETURNS trigger AS $body$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Fictional review evidence is immutable';
    END IF;
    IF NEW.state_digest !~ '^[0-9a-f]{64}$' OR NOT EXISTS (
        SELECT 1 FROM financial_aid_syntheticquestionnairedraft q
        JOIN financial_aid_aidapplication a ON a.id=q.application_id
        JOIN schools_household h ON h.id=a.household_id
        JOIN schools_academicyear y ON y.id=a.academic_year_id
        JOIN schools_school s ON s.id=a.school_id
        JOIN schools_householdaccess g ON g.household_id=h.id
        JOIN auth_user u ON u.id=g.user_id
        WHERE q.id=NEW.questionnaire_id AND q.revision=NEW.questionnaire_revision
          AND a.status='DRAFT' AND h.school_id=a.school_id AND y.school_id=a.school_id
          AND s.is_active AND h.is_active AND g.is_active AND u.is_active
          AND g.user_id=NEW.actor_user_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Invalid fictional review evidence';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
CREATE TRIGGER jireh_syn_review_guard
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_syntheticapplicationreview
FOR EACH ROW EXECUTE FUNCTION jireh_syn_review_guard();
"""
DROP = """
DROP TRIGGER IF EXISTS jireh_syn_review_guard ON financial_aid_syntheticapplicationreview;
DROP FUNCTION IF EXISTS jireh_syn_review_guard();
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
        ("financial_aid", "0008_synthetic_questionnaire"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SyntheticApplicationReview",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                        editable=False, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("questionnaire_revision", models.PositiveIntegerField()),
                ("state_digest", models.CharField(max_length=64)),
                ("disclosure_version", models.CharField(max_length=32, default="fictional-review-v1")),
                ("actor_user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                )),
                ("questionnaire", models.ForeignKey(
                    to="financial_aid.syntheticquestionnairedraft",
                    on_delete=django.db.models.deletion.PROTECT, related_name="reviews",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="syntheticapplicationreview",
            constraint=models.UniqueConstraint(
                fields=["questionnaire", "actor_user", "state_digest"],
                name="jireh_syn_review_actor_state_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticapplicationreview",
            constraint=models.CheckConstraint(
                condition=Q(questionnaire_revision__gt=0, disclosure_version="fictional-review-v1"),
                name="jireh_syn_review_revision_version",
            ),
        ),
        migrations.RunPython(install, remove),
    ]
