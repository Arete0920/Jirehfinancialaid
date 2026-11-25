"""Disposable director assertion verification, NOT a login or enrollment service.

Reuse the pure FIDO2 verifier, never the Arete operator registry or authority.
The caller must independently establish the password-stage identity and supply
its server-owned session key. A returned proof ID confers no session or access.
"""
import hashlib
import hmac
import os
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import DirectorWebAuthnChallenge, DirectorWebAuthnCredential, School, SchoolStaffAccess
from .operator_webauthn import _known_credential, begin_operator_assertion, verify_operator_assertion

_TEST_SETTINGS = frozenset({"jireh.schools.test_settings", "jireh.schools.postgres_test_settings"})
_LIFETIME = timedelta(minutes=5)
_SESSION_KEY = re.compile(r"\A[a-z0-9]{32}\Z")
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def _guard():
    startup = os.environ.get("DJANGO_SETTINGS_MODULE")
    if (getattr(settings, "JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE", False) is not True
            or startup not in _TEST_SETTINGS
            or getattr(settings, "SETTINGS_MODULE", None) not in (None, startup)):
        raise PermissionDenied("Director credential acceptance unavailable.")


def _session_digest(session_key):
    if not isinstance(session_key, str) or not _SESSION_KEY.fullmatch(session_key):
        raise PermissionDenied("Director credential acceptance unavailable.")
    return salted_hmac("jireh-director-assertion-v1", session_key, algorithm="sha256").hexdigest()


def _grant_locked(*, actor, school_id):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Director credential acceptance unavailable.")
    school = School.objects.select_for_update().filter(pk=school_id, is_active=True).first()
    if school is None:
        raise PermissionDenied("Director credential acceptance unavailable.")
    grant = SchoolStaffAccess.objects.select_for_update().filter(
        school=school, user_id=actor.pk, role=SchoolStaffAccess.ROLE_AID_DIRECTOR, is_active=True,
    ).first()
    account = get_user_model()._default_manager.select_for_update().filter(
        pk=actor.pk, is_active=True, is_staff=False, is_superuser=False,
    ).first()
    if grant is None or account is None:
        raise PermissionDenied("Director credential acceptance unavailable.")
    return grant


def _trusted_credential(*, grant, digest):
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return None
    credential = DirectorWebAuthnCredential.objects.select_for_update().filter(
        grant=grant, credential_id_digest=digest, enrollment_verified_at__isnull=False,
        revoked_at__isnull=True, rp_id=getattr(settings, "JIREH_DIRECTOR_WEBAUTHN_RP_ID", None),
    ).first()
    if credential is None or credential.enrollment_verified_at > timezone.now():
        return None
    try:
        actual = hashlib.sha256(_known_credential(bytes(credential.credential_data)).credential_id).hexdigest()
    except (TypeError, ValueError):
        return None
    return credential if hmac.compare_digest(actual, digest) else None


def begin_director_assertion(*, actor, school_id, session_key, credential_id_digest):
    _guard()
    binding = _session_digest(session_key)
    try:
        with transaction.atomic(durable=True):
            grant = _grant_locked(actor=actor, school_id=school_id)
            credential = _trusted_credential(grant=grant, digest=credential_id_digest)
            if credential is None:
                raise PermissionDenied("Director credential acceptance unavailable.")
            now = timezone.now()
            old = DirectorWebAuthnChallenge.objects.select_for_update().filter(
                credential=credential, closed_at__isnull=True,
            ).first()
            if old is not None:
                if now < old.expires_at:
                    raise PermissionDenied("Director challenge already pending.")
                old.closed_at = now
                old.save(update_fields=["closed_at", "updated_at"])
            options, state = begin_operator_assertion(
                rp_id=credential.rp_id, origin=f"https://{credential.rp_id}",
                credential_data=bytes(credential.credential_data),
            )
            row = DirectorWebAuthnChallenge.objects.create(
                credential=credential, session_digest=binding, challenge=state["challenge"],
                expires_at=now + _LIFETIME,
            )
            return options, row.pk
    except (DatabaseError, RuntimeError, ValidationError, ValueError):
        raise PermissionDenied("Director credential acceptance unavailable.") from None


def complete_director_assertion(*, actor, school_id, session_key, challenge_id, response):
    """Consume the challenge and advance its counter in one committed transaction."""
    _guard()
    binding = _session_digest(session_key)
    try:
        with transaction.atomic(durable=True):
            grant = _grant_locked(actor=actor, school_id=school_id)
            # Lock the credential before the challenge, as in begin. A wrong
            # actor, school or session cannot consume another caller's challenge.
            pointer = DirectorWebAuthnChallenge.objects.filter(
                pk=challenge_id, credential__grant=grant, session_digest=binding,
            ).values_list("credential__credential_id_digest", flat=True).first()
            if pointer is None:
                raise PermissionDenied("Director challenge unavailable.")
            credential = _trusted_credential(grant=grant, digest=pointer)
            row = DirectorWebAuthnChallenge.objects.select_for_update().filter(
                pk=challenge_id, credential__grant=grant, session_digest=binding, closed_at__isnull=True,
            ).first()
            if row is None:
                raise PermissionDenied("Director challenge unavailable.")
            now = timezone.now()
            row.closed_at = now
            if credential is not None and now < row.expires_at:
                try:
                    count = verify_operator_assertion(
                        rp_id=credential.rp_id, origin=f"https://{credential.rp_id}",
                        credential_data=bytes(credential.credential_data),
                        state={"challenge": row.challenge, "user_verification": "required"},
                        response=response, previous_sign_count=credential.sign_count,
                    )
                except (ValueError, TypeError, KeyError, AttributeError):
                    count = None
                if count is not None:
                    credential.sign_count = count
                    credential.save(update_fields=["sign_count", "updated_at"])
                    row.verified_at = now
                    row.verified_sign_count = count
            row.save(update_fields=["closed_at", "verified_at", "verified_sign_count", "updated_at"])
            verified = row.verified_at is not None
    except (DatabaseError, RuntimeError, ValidationError, ValueError):
        raise PermissionDenied("Director credential acceptance unavailable.") from None
    if not verified:
        raise PermissionDenied("Director assertion rejected.")
    return row.pk
