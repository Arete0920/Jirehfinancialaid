"""Disposable provisioning receipts; no runtime activation or live migration."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION jireh_synth_provisioning_protect()
            RETURNS trigger AS $body$
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Synthetic provisioning evidence is immutable';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM schools_schoolsetupintent i
                    JOIN schools_schoolpreparationevent e ON e.id = NEW.preparation_id
                    JOIN schools_school s ON s.id = NEW.school_id
                    JOIN schools_operatorwebauthnactionintent p
                        ON p.id = NEW.proposal_proof_id
                    JOIN schools_operatorwebauthnactionintent a
                        ON a.id = NEW.approval_proof_id
                    WHERE i.id = NEW.setup_id AND e.intent_id = i.id
                        AND e.actor_id = i.proposed_by_id AND e.action = 'PREPARED'
                        AND NOT EXISTS (
                            SELECT 1 FROM schools_schoolpreparationevent later
                            WHERE later.intent_id = i.id AND later.sequence > e.sequence
                        )
                        AND NOT s.is_active AND s.code LIKE 'synthetic-%'
                        AND p.operator_id = i.proposed_by_id
                        AND a.operator_id <> p.operator_id
                        AND p.action = 'SCHOOL_SETUP_PROPOSE'
                        AND a.action = 'SCHOOL_SETUP_APPROVE'
                        AND p.consumed_at IS NOT NULL AND a.consumed_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Invalid synthetic provisioning evidence';
                END IF;
                RETURN NEW;
            END;
            $body$ LANGUAGE plpgsql;
        """)
        cursor.execute(
            "CREATE TRIGGER jireh_synth_provisioning_guard "
            "BEFORE INSERT OR UPDATE OR DELETE ON schools_syntheticschoolprovisioningreceipt "
            "FOR EACH ROW EXECUTE FUNCTION jireh_synth_provisioning_protect()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_synth_provisioning_guard "
            "ON schools_syntheticschoolprovisioningreceipt"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_synth_provisioning_protect()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0025_school_setup_action_choices"),
    ]
    operations = [
        migrations.CreateModel(
            name="SyntheticSchoolProvisioningReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reference_digest", models.CharField(max_length=64)),
                ("setup", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_provisioning_receipt",
                    to="schools.schoolsetupintent",
                )),
                ("preparation", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_provisioning_receipt",
                    to="schools.schoolpreparationevent",
                )),
                ("school", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_provisioning_receipt",
                    to="schools.school",
                )),
                ("proposal_proof", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_setup_proposal_receipt",
                    to="schools.operatorwebauthnactionintent",
                )),
                ("approval_proof", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="synthetic_setup_approval_receipt",
                    to="schools.operatorwebauthnactionintent",
                )),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(proposal_proof=models.F("approval_proof")),
                        name="jireh_synth_setup_distinct_proofs",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(reference_digest__regex=r"^[0-9a-f]{64}$"),
                        name="jireh_synth_setup_reference_digest",
                    ),
                ],
            },
        ),
        migrations.RunPython(install, remove),
    ]
