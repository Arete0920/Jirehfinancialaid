"""Disposable encrypted questionnaire persistence; no runtime route."""
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from jireh.schools.models import HouseholdAccess, School
from .fictional_school_questions import school_questions_for_draft
from .models import SyntheticQuestionnaireDraft, SyntheticQuestionnaireEvent
from .questionnaire_candidate import (
    validate_v1_field_catalog, validate_v1_financial_candidate,
)
from .questionnaire_validation import QuestionnaireValidationError
from .services import _require_existing_draft

_TEST_SETTINGS = frozenset({
    "jireh.schools.test_settings", "jireh.schools.postgres_test_settings",
})
_MAX_BYTES = 32768
_MAX_REVISION = 2147483647
_SECTIONS = ("income", "assets", "liabilities", "expenses")


@dataclass(frozen=True, repr=False)
class FictionalQuestionnairePolicy:
    reporting_year: int
    min_cents: int
    max_cents: int
    categories: tuple
    member_ids: tuple


def _guard(key):
    startup = os.environ.get("DJANGO_SETTINGS_MODULE")
    # Django override_settings uses a UserSettingsHolder whose SETTINGS_MODULE
    # is None. Still require a known disposable startup module and explicit opt-in.
    disposable_demo = (
        startup == "jireh.schools.demo_settings"
        and os.environ.get("JIREH_LOCAL_DEMO_ONLY") == "YES-SYNTHETIC-ONLY"
        and settings.ROOT_URLCONF == "jireh.schools.demo_urls"
        and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
        and str(settings.DATABASES["default"]["NAME"]) == os.environ.get("JIREH_LOCAL_DEMO_DB")
    )
    if (
        (startup not in _TEST_SETTINGS and not disposable_demo)
        or settings.SETTINGS_MODULE not in (None, startup)
        or getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", False) is not True
    ):
        raise PermissionDenied("Fictional questionnaire storage unavailable.")
    if type(key) is not bytes or len(key) != 32:
        raise QuestionnaireValidationError("questionnaire_key_invalid")


def _locked_draft(user, school_id, household_id, academic_year_id):
    # The school lock matches grant_admin's revocation order.
    draft = _require_existing_draft(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id,
    )
    if not School.objects.select_for_update().filter(
        pk=draft.school_id, is_active=True,
    ).exists():
        raise Http404("Draft not found.")
    if not HouseholdAccess.objects.select_for_update().filter(
        household_id=draft.household_id, household__is_active=True,
        household__school_id=draft.school_id, user_id=user.pk,
        user__is_active=True, is_active=True,
    ).exists():
        raise Http404("Draft not found.")
    return _require_existing_draft(
        user=user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id, lock=True,
    )


def _encode(answers, catalog, policy, *, draft, previous):
    if type(policy) is not FictionalQuestionnairePolicy:
        raise QuestionnaireValidationError("questionnaire_policy_invalid")
    if type(answers) is not dict or set(answers) - {*_SECTIONS, "school_questions"}:
        raise QuestionnaireValidationError("questionnaire_sections_invalid")
    if type(policy.categories) is not tuple or len(policy.categories) != 4:
        raise QuestionnaireValidationError("questionnaire_policy_invalid")
    # Empty snapshots also require the frozen development catalog.
    validate_v1_field_catalog(catalog)
    for section, rows in answers.items():
        if section == "school_questions":
            continue
        if type(rows) is not list or len(rows) > 32:
            raise QuestionnaireValidationError("questionnaire_rows_invalid")
        for row in rows:
            validate_v1_financial_candidate(
                catalog=catalog, section=section, record=row,
                approved_categories=policy.categories[_SECTIONS.index(section)],
                min_cents=policy.min_cents, max_cents=policy.max_cents,
                reporting_year=policy.reporting_year,
                authorized_member_ids=policy.member_ids,
            )
    if "school_questions" in answers or "school_questions" in previous:
        saved_questions = previous.get("school_questions", [])
        question_rows = answers.get("school_questions", saved_questions)
        school_questions_for_draft(draft, saved_questions).validate(question_rows)
        answers = {**answers, "school_questions": question_rows}
    try:
        payload = json.dumps(
            answers, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise QuestionnaireValidationError("questionnaire_encoding_invalid") from None
    if len(payload) > _MAX_BYTES:
        raise QuestionnaireValidationError("questionnaire_size_invalid")
    return payload


def _aad(draft, revision):
    return (
        f"jireh:fictional-questionnaire:v1:{draft.school_id}:"
        f"{draft.household_id}:{draft.academic_year_id}:{draft.pk}:{revision}"
    ).encode("ascii")


def _decrypt(row, draft, key):
    data = bytes(row.ciphertext)
    if not 28 < len(data) <= _MAX_BYTES + 28:
        raise QuestionnaireValidationError("questionnaire_integrity_failed")
    try:
        plain = AESGCM(key).decrypt(data[:12], data[12:], _aad(draft, row.revision))
        return json.loads(plain)
    except (InvalidTag, ValueError, UnicodeDecodeError):
        raise QuestionnaireValidationError("questionnaire_integrity_failed") from None


@transaction.atomic
def save_fictional_questionnaire(
    *, user, school_id, household_id, academic_year_id, answers,
    expected_revision, catalog, policy, key,
):
    """Replace a synthetic snapshot atomically; stale writes never overwrite it."""
    _guard(key)
    draft = _locked_draft(user, school_id, household_id, academic_year_id)
    if type(expected_revision) is not int or not 0 <= expected_revision < _MAX_REVISION:
        raise QuestionnaireValidationError("questionnaire_revision_invalid")
    row = SyntheticQuestionnaireDraft.objects.filter(application=draft).first()
    current = row.revision if row else 0
    if current != expected_revision:
        raise QuestionnaireValidationError("questionnaire_revision_conflict")
    previous = _decrypt(row, draft, key) if row is not None else {}
    payload = _encode(answers, catalog, policy, draft=draft, previous=previous)
    revision = current + 1
    nonce = os.urandom(12)
    ciphertext = nonce + AESGCM(key).encrypt(nonce, payload, _aad(draft, revision))
    if row is None:
        row = SyntheticQuestionnaireDraft.objects.create(
            application=draft, revision=revision, ciphertext=ciphertext,
        )
    else:
        row.revision = revision
        row.ciphertext = ciphertext
        row.save(update_fields=["revision", "ciphertext", "updated_at"])
    SyntheticQuestionnaireEvent.objects.create(
        questionnaire=row, actor_user=user, revision=revision,
    )
    return revision


@transaction.atomic
def read_fictional_questionnaire(
    *, user, school_id, household_id, academic_year_id, key,
):
    """Return an authorized snapshot, not a verified or submitted application."""
    _guard(key)
    draft = _locked_draft(user, school_id, household_id, academic_year_id)
    row = SyntheticQuestionnaireDraft.objects.filter(application=draft).first()
    if row is None:
        return 0, {}
    return row.revision, _decrypt(row, draft, key)
