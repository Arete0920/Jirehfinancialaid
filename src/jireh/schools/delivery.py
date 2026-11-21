"""Fail-closed SMTP delivery for standalone Jireh invitation secrets.

Internal service only. No endpoints, provider credentials, live configuration,
background queues, or public account onboarding are enabled here.

Django's default SMTP settings are NOT safe: transport stays disabled unless
explicitly opted in with an authenticated TLS SMTP provider and bounded
timeout. The raw secrets live in memory solely for a single send operation;
both delivery functions return an identifier, never a secret.

A successful SMTP acceptance is not proof of delivery to the human recipient.
A family still needs a separate authenticated redemption step.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .invitations import issue_household_invitation, revoke_household_invitation
from .models import HouseholdInvitation, MailboxChallenge
from .redemption import (
    _authenticated,
    _token_digest,
    issue_mailbox_challenge,
)


class DeliveryNotConfigured(ImproperlyConfigured):
    """Email delivery deliberately remains unavailable until certified."""


class DeliveryFailure(RuntimeError):
    """A token was not reliably delivered or cleanup requires review."""


def _require_secure_delivery():
    """Reject test/console backends and default unencrypted SMTP settings.

    The opt-in flag is intentionally not exposed in runtime/settings.py;
    the deployment owner must separately approve and configure any transport.
    """
    if getattr(settings, "JIREH_EMAIL_DELIVERY_ENABLED", False) is not True:
        raise DeliveryNotConfigured("Jireh email delivery is disabled.")

    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        raise DeliveryNotConfigured("Only the authenticated SMTP backend is permitted.")

    tls = settings.EMAIL_USE_TLS is True
    ssl = settings.EMAIL_USE_SSL is True
    if tls == ssl:
        raise DeliveryNotConfigured("Exactly one SMTP TLS mode must be enabled.")

    port = settings.EMAIL_PORT
    if type(port) is not int or port != (587 if tls else 465):
        raise DeliveryNotConfigured("The selected SMTP TLS mode requires its secure port.")

    host = settings.EMAIL_HOST
    if (not isinstance(host, str) or not host or host != host.strip()
            or host.lower() in {"localhost", "127.0.0.1", "::1"}):
        raise DeliveryNotConfigured("A remote SMTP hostname is required.")

    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise DeliveryNotConfigured("SMTP authentication must be configured.")

    timeout = settings.EMAIL_TIMEOUT
    if type(timeout) not in (int, float) or not (0 < timeout <= 10):
        raise DeliveryNotConfigured("An SMTP timeout of 10 seconds or less is required.")

    sender = getattr(settings, "JIREH_EMAIL_FROM", None)
    if not isinstance(sender, str) or not sender or sender != sender.strip():
        raise DeliveryNotConfigured("A dedicated Jireh sender address is required.")
    try:
        validate_email(sender)
    except Exception:
        raise DeliveryNotConfigured("A valid Jireh sender address is required.") from None

    return sender


def _send_one_secret(*, to, token, subject, purpose, sender):
    # No URLs with credentials; URLs can leak through logs and referrers.
    body = (
        "Jireh Financial Aid\n\n"
        f"Your {purpose} code is:\n\n{token}\n\n"
        "Use this code only in the authenticated Jireh invitation process. "
        "It expires automatically. If you did not request it, ignore this message.\n"
        "Never share this code with an unexpected caller.\n"
    )
    try:
        sent = EmailMessage(
            subject=subject,
            body=body,
            from_email=sender,
            to=[to],
        ).send(fail_silently=False)
    except Exception:
        # Do not retain provider exceptions: providers may echo message bodies,
        # usernames, recipient data, or authentication diagnostics.
        raise DeliveryFailure("Jireh email delivery was not confirmed.") from None
    if sent != 1:
        raise DeliveryFailure("Jireh email delivery was not confirmed.")


def deliver_household_invitation(*, actor, school_id, household_id, email):
    """Issue and send a school-authorized invitation without returning its code.

    Failed or ambiguous SMTP sends trigger a separately audited cancellation.
    If SMTP accepted the message but final delivery failed, the code may still
    be cancelled on a future retry by the school's director.
    """
    sender = _require_secure_delivery()  # no DB changes before policy check
    invitation, token = issue_household_invitation(
        actor=actor, school_id=school_id, household_id=household_id, email=email,
    )
    try:
        _send_one_secret(
            to=invitation.email,
            token=token,
            subject="Jireh Financial Aid invitation",
            purpose="household invitation",
            sender=sender,
        )
    except DeliveryFailure:
        try:
            revoke_household_invitation(
                actor=actor, school_id=school_id,
                invitation_id=invitation.pk,
            )
        except Exception:
            raise DeliveryFailure(
                "Jireh delivery failed; invitation cancellation requires review."
            ) from None
        raise

    return invitation.pk


def _consume_failed_challenge(challenge_id):
    """Make an ambiguously delivered mailbox code unusable before retry."""
    try:
        with transaction.atomic():
            challenge = MailboxChallenge.objects.select_for_update().get(
                pk=challenge_id
            )
            if challenge.consumed_at is None:
                challenge.consumed_at = timezone.now()
                challenge.save(update_fields=["consumed_at", "updated_at"])
    except Exception:
        raise DeliveryFailure(
            "Jireh delivery failed; mailbox challenge cancellation requires review."
        ) from None


def deliver_mailbox_challenge(
    *, user, school_id, household_id, invitation_token
):
    """Deliver a short-lived mailbox proof only after presenting an invitation.

    The email recipient is taken from the verified pending invitation and
    CANNOT be supplied by the authenticated user. The mailbox code is bound
    to that authenticated user by issue_mailbox_challenge.
    """
    sender = _require_secure_delivery()
    _authenticated(user)
    digest = _token_digest(invitation_token)
    if not school_id or not household_id:
        raise Http404("Invitation not found.")

    invitation = (
        HouseholdInvitation.objects.for_school(school_id)
        .filter(
            household_id=household_id,
            household__school_id=school_id,
            school__is_active=True,
            household__is_active=True,
            token_digest=digest,
            revoked_at__isnull=True,
            redeemed_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if invitation is None:
        raise Http404("Invitation not found.")

    challenge, token = issue_mailbox_challenge(
        user=user, email=invitation.email
    )
    try:
        _send_one_secret(
            to=invitation.email,
            token=token,
            subject="Jireh Financial Aid email verification",
            purpose="mailbox verification",
            sender=sender,
        )
    except DeliveryFailure:
        _consume_failed_challenge(challenge.pk)
        raise

    return challenge.pk
