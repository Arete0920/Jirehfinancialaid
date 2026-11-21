"""Account-verified contact and recovery audit foundation; no public routes."""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


RECOVERY_GUARDS = """
CREATE FUNCTION jireh_recovery_row_protect() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'Jireh recovery evidence cannot be deleted';
    END IF;
    IF TG_TABLE_NAME = 'schools_verifiedrecoverycontact' THEN
        IF NOT EXISTS (
            SELECT 1 FROM schools_mailboxchallenge
            WHERE id = NEW.proof_id AND user_id = NEW.user_id
              AND email = NEW.email AND consumed_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Jireh recovery contact proof mismatch';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF ROW(NEW.user_id, NEW.proof_id, NEW.email, NEW.verified_at)
              IS DISTINCT FROM
               ROW(OLD.user_id, OLD.proof_id, OLD.email, OLD.verified_at) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'Jireh recovery contact is immutable';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'schools_passwordrecoverychallenge' THEN
        IF NOT EXISTS (
            SELECT 1 FROM schools_verifiedrecoverycontact
            WHERE id = NEW.contact_id AND user_id = NEW.user_id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Jireh recovery challenge account mismatch';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF ROW(NEW.user_id, NEW.contact_id, NEW.token_digest, NEW.expires_at)
              IS DISTINCT FROM
               ROW(OLD.user_id, OLD.contact_id, OLD.token_digest, OLD.expires_at) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'Jireh recovery challenge identity is immutable';
            END IF;
            IF OLD.consumed_at IS NOT NULL AND
               ROW(NEW.consumed_at, NEW.password_changed_at)
                 IS DISTINCT FROM
               ROW(OLD.consumed_at, OLD.password_changed_at) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'Jireh consumed recovery challenge is immutable';
            END IF;
        END IF;
        IF NEW.password_changed_at IS NOT NULL AND NEW.consumed_at IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'Jireh completed recovery must consume its challenge';
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
        cursor.execute(RECOVERY_GUARDS)
        for table in ("schools_verifiedrecoverycontact",
                      "schools_passwordrecoverychallenge"):
            cursor.execute(
                "CREATE TRIGGER jireh_" + table + "_protect "
                "BEFORE UPDATE OR DELETE ON " + table +
                " FOR EACH ROW EXECUTE FUNCTION jireh_recovery_row_protect()"
            )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in ("schools_verifiedrecoverycontact",
                      "schools_passwordrecoverychallenge"):
            cursor.execute(
                "DROP TRIGGER IF EXISTS jireh_" + table + "_protect ON " + table
            )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_recovery_row_protect()")


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0010_login_attempt_budget"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VerifiedRecoveryContact",
            fields=[
                ("id", models.UUIDField(
                    primary_key=True, default=uuid.uuid4,
                    editable=False, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email", models.EmailField(max_length=254)),
                ("verified_at", models.DateTimeField()),
                ("user", models.OneToOneField(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_recovery_contact",
                )),
                ("proof", models.OneToOneField(
                    to="schools.mailboxchallenge",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="recovery_contact",
                )),
            ],
        ),
        migrations.CreateModel(
            name="PasswordRecoveryChallenge",
            fields=[
                ("id", models.UUIDField(
                    primary_key=True, default=uuid.uuid4,
                    editable=False, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(null=True, blank=True)),
                ("password_changed_at", models.DateTimeField(
                    null=True, blank=True,
                )),
                ("user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_password_recovery_challenges",
                )),
                ("contact", models.ForeignKey(
                    to="schools.verifiedrecoverycontact",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="recovery_challenges",
                )),
            ],
            options={"constraints": [
                models.UniqueConstraint(
                    fields=["user"],
                    condition=Q(consumed_at__isnull=True),
                    name="jireh_one_open_recovery_challenge",
                ),
            ]},
        ),
        migrations.CreateModel(
            name="RecoveryAttemptBudget",
            fields=[
                ("id", models.UUIDField(
                    primary_key=True, default=uuid.uuid4,
                    editable=False, serialize=False,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("identifier_digest", models.CharField(max_length=64)),
                ("purpose", models.CharField(
                    max_length=8,
                    choices=[("ISSUE", "Issue"), ("CONFIRM", "Confirm")],
                )),
                ("window_started_at", models.DateTimeField()),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"constraints": [
                models.UniqueConstraint(
                    fields=["identifier_digest", "purpose"],
                    name="jireh_recovery_budget_identity_purpose",
                ),
                models.CheckConstraint(
                    condition=Q(attempt_count__lte=10),
                    name="jireh_recovery_budget_max10",
                ),
            ]},
        ),
        migrations.RunPython(install, remove),
    ]
