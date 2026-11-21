"""One-use verified redemption schema and PostgreSQL immutability guards.

No public routes, mail delivery, login provider, or production activation.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


INVITATION_GUARD = """
CREATE OR REPLACE FUNCTION jireh_guard_household_invitation() RETURNS trigger AS $body$
DECLARE v_school uuid;
BEGIN
    SELECT school_id INTO v_school FROM schools_household
      WHERE id = NEW.household_id;
    IF v_school IS DISTINCT FROM NEW.school_id THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh invitation household school mismatch';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.id, NEW.created_at, NEW.school_id, NEW.household_id,
            NEW.email, NEW.token_digest, NEW.invited_by_id, NEW.expires_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.created_at, OLD.school_id, OLD.household_id,
            OLD.email, OLD.token_digest, OLD.invited_by_id, OLD.expires_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh invitation identity is immutable';
        END IF;
        IF OLD.revoked_at IS NOT NULL AND
           NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh revoked invitation cannot be changed';
        END IF;
        IF OLD.redeemed_at IS NOT NULL AND
           ROW(NEW.redeemed_at, NEW.redeemed_by_id, NEW.revoked_at)
             IS DISTINCT FROM
           ROW(OLD.redeemed_at, OLD.redeemed_by_id, OLD.revoked_at) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh redeemed invitation cannot be changed';
        END IF;
        IF OLD.revoked_at IS NOT NULL AND
           NEW.redeemed_at IS DISTINCT FROM OLD.redeemed_at THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh revoked invitation cannot be redeemed';
        END IF;
    END IF;
    IF NEW.revoked_at IS NOT NULL AND NEW.redeemed_at IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh invitation cannot be revoked and redeemed';
    END IF;
    IF (NEW.redeemed_at IS NULL) <> (NEW.redeemed_by_id IS NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh redemption must identify user and time';
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

MAILBOX_GUARD = """
CREATE FUNCTION jireh_protect_mailbox_challenge() RETURNS trigger AS $body$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh mailbox challenges cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.id, NEW.created_at, NEW.user_id, NEW.email,
            NEW.token_digest, NEW.expires_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.created_at, OLD.user_id, OLD.email,
            OLD.token_digest, OLD.expires_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh mailbox challenge identity is immutable';
        END IF;
        IF OLD.consumed_at IS NOT NULL AND
           NEW.consumed_at IS DISTINCT FROM OLD.consumed_at THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh used mailbox challenge cannot be reactivated';
        END IF;
    END IF;
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
"""

OLD_INVITATION_GUARD = """
CREATE OR REPLACE FUNCTION jireh_guard_household_invitation() RETURNS trigger AS $body$
DECLARE
    v_school_id uuid;
BEGIN
    SELECT school_id INTO v_school_id
      FROM schools_household WHERE id = NEW.household_id;
    IF v_school_id IS DISTINCT FROM NEW.school_id THEN
        RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='Jireh invitation household school mismatch';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.id, NEW.created_at, NEW.school_id, NEW.household_id,
            NEW.email, NEW.token_digest, NEW.invited_by_id, NEW.expires_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.created_at, OLD.school_id, OLD.household_id,
            OLD.email, OLD.token_digest, OLD.invited_by_id, OLD.expires_at
        ) THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh invitation identity is immutable';
        END IF;
        IF OLD.revoked_at IS NOT NULL AND
           NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Jireh revoked invitation cannot be changed';
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
        cursor.execute(INVITATION_GUARD)
        cursor.execute(MAILBOX_GUARD)
        cursor.execute(
            "CREATE TRIGGER jireh_mailbox_challenge_protect "
            "BEFORE UPDATE OR DELETE ON schools_mailboxchallenge "
            "FOR EACH ROW EXECUTE FUNCTION jireh_protect_mailbox_challenge()"
        )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS jireh_mailbox_challenge_protect "
            "ON schools_mailboxchallenge"
        )
        cursor.execute("DROP FUNCTION IF EXISTS jireh_protect_mailbox_challenge()")
        cursor.execute(OLD_INVITATION_GUARD)


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0007_household_invitations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="householdinvitation",
            name="redeemed_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="householdinvitation",
            name="redeemed_by",
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.PROTECT,
                null=True, blank=True,
                related_name="jireh_household_invitations_redeemed",
            ),
        ),
        migrations.AlterField(
            model_name="schoolinvitationevent",
            name="action",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("ISSUED", "Issued"),
                    ("REVOKED", "Revoked"),
                    ("REDEEMED", "Redeemed"),
                ],
            ),
        ),
        migrations.RemoveConstraint(
            model_name="householdinvitation",
            name="jireh_open_household_invite",
        ),
        migrations.AddConstraint(
            model_name="householdinvitation",
            constraint=models.UniqueConstraint(
                fields=["household", "email"],
                condition=Q(revoked_at__isnull=True, redeemed_at__isnull=True),
                name="jireh_open_household_invite",
            ),
        ),
        migrations.CreateModel(
            name="MailboxChallenge",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False,
                                        editable=False, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email", models.EmailField(max_length=254)),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(null=True, blank=True)),
                ("user", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="jireh_mailbox_challenges",
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["user", "email"],
                        condition=Q(consumed_at__isnull=True),
                        name="jireh_one_open_mailbox_proof",
                    )
                ]
            },
        ),
        migrations.RunPython(install, remove),
    ]
