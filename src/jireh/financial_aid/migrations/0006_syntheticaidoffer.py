"""One fictional $250 offered-aid record with raw-write integrity proof.

This model must not be used to make real awards, tuition credits, disbursements,
payment claims or institutionally binding aid decisions.
"""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


INSTALL = """
CREATE FUNCTION jireh_syn_offer_integrity() RETURNS trigger AS $body$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Fictional aid offer evidence is immutable';
    END IF;
    IF NEW.bucket IS DISTINCT FROM 'need'
       OR NEW.amount_cents IS DISTINCT FROM 25000 THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Only the synthetic $250 example is permitted';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM financial_aid_aidapplication app
          JOIN financial_aid_aidapplicationstudent sel
            ON sel.id = NEW.student_selection_id
           AND sel.application_id = app.id
          JOIN financial_aid_syntheticaidsubmission receipt
            ON receipt.application_id = app.id
          JOIN schools_school school ON school.id = app.school_id
          JOIN schools_academicyear year
            ON year.id = app.academic_year_id AND year.school_id = app.school_id
          JOIN schools_schoolstaffaccess staff
            ON staff.school_id = app.school_id
           AND staff.user_id = NEW.actor_user_id
           AND staff.is_active
           AND staff.role = 'AID_DIRECTOR'
         WHERE app.id = NEW.application_id AND app.status = 'DRAFT'
           AND school.is_active
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Fictional offer school, officer or submission mismatch';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
CREATE TRIGGER jireh_syn_offer_freeze
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_syntheticaidoffer
FOR EACH ROW EXECUTE FUNCTION jireh_syn_offer_integrity();
"""

REMOVE = """
DROP TRIGGER IF EXISTS jireh_syn_offer_freeze ON financial_aid_syntheticaidoffer;
DROP FUNCTION IF EXISTS jireh_syn_offer_integrity();
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
        ("financial_aid", "0005_syntheticaidsubmission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SyntheticAidOffer",
            fields=[
                ("id", models.UUIDField(
                    primary_key=True, default=uuid.uuid4, editable=False,
                    serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bucket", models.CharField(max_length=16, default="need")),
                ("amount_cents", models.PositiveIntegerField(default=25000)),
                ("application", models.ForeignKey(
                    to="financial_aid.aidapplication",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_offers",
                )),
                ("student_selection", models.OneToOneField(
                    to="financial_aid.aidapplicationstudent",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_offer",
                )),
                ("actor_user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_synthetic_offers_created",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="syntheticaidoffer",
            constraint=models.CheckConstraint(
                condition=Q(bucket="need"), name="jireh_syn_offer_bucket",
            ),
        ),
        migrations.AddConstraint(
            model_name="syntheticaidoffer",
            constraint=models.CheckConstraint(
                condition=Q(amount_cents=25000),
                name="jireh_syn_offer_fixed_amount",
            ),
        ),
        migrations.RunPython(install, remove),
    ]
