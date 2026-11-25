"""Install an append-only disposable decision journal, never a live award ledger."""
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


SQL = """
CREATE FUNCTION jireh_need_decision_protect() RETURNS trigger AS $body$
DECLARE
    target_school uuid;
    target_year uuid;
    budget numeric;
    other_amount numeric;
    last_revision integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Fictional need decisions are immutable';
    END IF;
    SELECT school_id, academic_year_id INTO target_school, target_year
        FROM financial_aid_aidapplication WHERE id=NEW.application_id;
    -- Same school-first locking order as authorized rehearsal services.
    PERFORM 1 FROM schools_school WHERE id=target_school FOR UPDATE;
    PERFORM 1 FROM schools_schoolstaffaccess WHERE school_id=target_school AND user_id=NEW.actor_user_id FOR UPDATE;
    PERFORM 1 FROM auth_user WHERE id=NEW.actor_user_id FOR UPDATE;
    PERFORM 1 FROM auth_user_user_permissions up
        JOIN auth_permission p ON p.id=up.permission_id
        JOIN django_content_type t ON t.id=p.content_type_id
        WHERE up.user_id=NEW.actor_user_id AND t.app_label='financial_aid'
          AND t.model='fictionalneeddecision' AND p.codename='add_fictionalneeddecision'
        FOR UPDATE OF up;
    PERFORM 1 FROM schools_academicyear WHERE id=target_year FOR UPDATE;
    PERFORM 1 FROM financial_aid_aidapplication WHERE id=NEW.application_id FOR UPDATE;
    IF NOT EXISTS (
        SELECT 1 FROM financial_aid_aidapplication a
        JOIN schools_school s ON s.id=a.school_id
        JOIN schools_academicyear y ON y.id=a.academic_year_id AND y.school_id=s.id
        JOIN schools_household h ON h.id=a.household_id AND h.school_id=s.id
        JOIN financial_aid_syntheticquestionnairedraft q ON q.application_id=a.id
        JOIN financial_aid_syntheticaidsubmission r ON r.application_id=a.id
        JOIN financial_aid_fictionalschoolplanrevision p ON p.school_id=s.id AND p.academic_year_id=y.id
        JOIN schools_schoolstaffaccess g ON g.school_id=s.id AND g.user_id=NEW.actor_user_id
        JOIN auth_user u ON u.id=g.user_id
        JOIN auth_user_user_permissions up ON up.user_id=u.id
        JOIN auth_permission ap ON ap.id=up.permission_id
        JOIN django_content_type ct ON ct.id=ap.content_type_id
        JOIN schools_householdaccess hg ON hg.household_id=h.id AND hg.user_id=r.actor_user_id
        JOIN auth_user hu ON hu.id=hg.user_id
        WHERE a.id=NEW.application_id AND a.status='DRAFT'
          AND s.code='local-jireh-school-a' AND s.is_active AND h.is_active
          AND q.id=NEW.questionnaire_id AND q.revision=NEW.questionnaire_revision
          AND r.id=NEW.receipt_id AND r.accuracy_attested AND r.consent_version='synthetic-demo-v1'
          AND hg.is_active AND hu.is_active
          AND p.id=NEW.plan_id AND p.revision=(SELECT MAX(x.revision)
            FROM financial_aid_fictionalschoolplanrevision x WHERE x.academic_year_id=y.id)
          AND u.is_active AND g.is_active AND g.role='AID_DIRECTOR'
          AND ct.app_label='financial_aid' AND ct.model='fictionalneeddecision'
          AND ap.codename='add_fictionalneeddecision'
          AND NOT EXISTS (SELECT 1 FROM schools_fictionalcontributorexception m
            WHERE m.application_id=a.id AND NOT EXISTS
              (SELECT 1 FROM schools_fictionalcontributordecision d WHERE d.marker_id=m.id))
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Invalid fictional need decision scope';
    END IF;
    SELECT COALESCE(MAX(revision),0) INTO last_revision
        FROM financial_aid_fictionalneeddecision WHERE application_id=NEW.application_id;
    IF NEW.revision <> last_revision+1 THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Invalid fictional decision revision';
    END IF;
    SELECT (plan_payload->>'annual_aid_budget_cents')::numeric INTO budget
        FROM financial_aid_fictionalschoolplanrevision WHERE id=NEW.plan_id;
    SELECT COALESCE(SUM(v.amount_cents),0) INTO other_amount FROM (
        SELECT DISTINCT ON (d.application_id) d.amount_cents
        FROM financial_aid_fictionalneeddecision d JOIN financial_aid_aidapplication a ON a.id=d.application_id
        WHERE a.school_id=target_school AND a.academic_year_id=target_year AND a.id<>NEW.application_id
        ORDER BY d.application_id,d.revision DESC
    ) v;
    IF budget IS NULL OR NEW.amount_cents+other_amount>budget
        OR NEW.remaining_budget_cents<>budget-NEW.amount_cents-other_amount
        OR NEW.dataset_sha256<>'10dc4f12ec5be0757c04de8237e9bb4c96d3a136ade0be55add75f2418d71fae' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Invalid fictional budget or dataset';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
CREATE TRIGGER jireh_need_decision_protect
BEFORE INSERT OR UPDATE OR DELETE ON financial_aid_fictionalneeddecision
FOR EACH ROW EXECUTE FUNCTION jireh_need_decision_protect();
"""
DROP = """
DROP TRIGGER IF EXISTS jireh_need_decision_protect ON financial_aid_fictionalneeddecision;
DROP FUNCTION IF EXISTS jireh_need_decision_protect();
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [
        ("financial_aid", "0010_fictional_school_plan_revision"),
        ("schools", "0028_fictional_contributor_decision"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="FictionalNeedDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("questionnaire_revision", models.PositiveIntegerField()),
                ("revision", models.PositiveIntegerField()),
                ("amount_cents", models.PositiveBigIntegerField()),
                ("need_cents", models.PositiveBigIntegerField()),
                ("remaining_budget_cents", models.PositiveBigIntegerField()),
                ("calculation_version", models.CharField(max_length=64)),
                ("dataset_sha256", models.CharField(max_length=64)),
                ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="financial_aid.aidapplication")),
                ("questionnaire", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="financial_aid.syntheticquestionnairedraft")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="financial_aid.fictionalschoolplanrevision")),
                ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="financial_aid.syntheticaidsubmission")),
                ("actor_user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("application", "revision"), name="jireh_need_decision_revision"),
                models.CheckConstraint(condition=models.Q(
                    ("questionnaire_revision__gt", 0), ("revision__gt", 0),
                    models.Q(("revision__gt", 1), ("amount_cents__gt", 0), _connector="OR"),
                    ("amount_cents__lte", models.F("need_cents")),
                    ("calculation_version", "fictional-regional-need-v1"),
                ), name="jireh_need_decision_valid"),
            ]},
        ),
        migrations.RunPython(install, remove),
    ]
