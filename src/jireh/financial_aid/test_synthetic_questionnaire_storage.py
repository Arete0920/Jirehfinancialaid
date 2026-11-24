"""Encrypted synthetic questionnaire acceptance in disposable databases only."""
import copy
import json
import os
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, override_settings

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.grant_admin import revoke_household_access
from jireh.schools.models import Household, HouseholdAccess, Student
from jireh.schools.services import link_student_to_household
from .models import AidApplication, SyntheticQuestionnaireDraft, SyntheticQuestionnaireEvent
from .questionnaire_validation import QuestionnaireValidationError
from .services import get_or_create_annual_draft
from .synthetic_questionnaire_storage import (
    FictionalQuestionnairePolicy,
    read_fictional_questionnaire,
    save_fictional_questionnaire,
)


@override_settings(JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True)
class FictionalQuestionnaireStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.separate = Household.objects.create(
            school=cls.fixture["school_a"], name="Fictional separate household",
        )
        cls.separate_parent = get_user_model().objects.create_user(
            username="fictional-separate-parent",
        )
        HouseholdAccess.objects.create(user=cls.separate_parent, household=cls.separate)
        child = Student.objects.get(school=cls.fixture["school_a"], first_name="Jordan")
        link_student_to_household(
            school_id=child.school_id, household_id=cls.separate.pk, student_id=child.pk,
        )
        cls.draft = get_or_create_annual_draft(
            user=cls.fixture["parent"], school_id=cls.fixture["school_a"].pk,
            household_id=cls.fixture["household_a"].pk,
            academic_year_id=cls.fixture["year_a"].pk,
        )
        cls.other_draft = get_or_create_annual_draft(
            user=cls.separate_parent, school_id=cls.fixture["school_a"].pk,
            household_id=cls.separate.pk, academic_year_id=cls.fixture["year_a"].pk,
        )

    def setUp(self):
        self.key = AESGCM.generate_key(bit_length=256)
        self.member = str(uuid4())
        self.catalog = json.loads(
            (Path(__file__).resolve().parents[3] / "docs" /
             "questionnaire_v1_field_catalog.json").read_text(encoding="utf-8")
        )
        self.policy = FictionalQuestionnairePolicy(
            reporting_year=2026, min_cents=0, max_cents=100000000,
            categories=(("EMPLOYMENT",), ("CASH",), ("MORTGAGE",), ("HOUSING",)),
            member_ids=(self.member,),
        )
        self.answers = {
            "income": [{"category": "EMPLOYMENT", "amount": 4567890,
                        "period_start": "2026-01-01", "period_end": "2026-12-31",
                        "contributor_id": self.member}],
            "assets": [{"category": "CASH", "balance": 0, "as_of_date": "2026-06-30",
                        "owner_member_id": self.member}],
            "liabilities": [{"category": "MORTGAGE", "balance": 123456,
                             "as_of_date": "2026-06-30", "responsible_member_id": self.member}],
            "expenses": [{"category": "HOUSING", "amount": 98765,
                          "period_start": "2026-01-01", "period_end": "2026-01-31"}],
        }

    def scope(self, **changes):
        params = dict(
            user=self.fixture["parent"], school_id=self.draft.school_id,
            household_id=self.draft.household_id, academic_year_id=self.draft.academic_year_id,
            key=self.key,
        )
        params.update(changes)
        return params

    def save(self, revision=0, **changes):
        params = dict(
            expected_revision=revision, answers=self.answers,
            catalog=self.catalog, policy=self.policy, **self.scope(),
        )
        params.update(changes)
        return save_fictional_questionnaire(**params)

    def test_save_resume_correct_clear_and_metadata_only_history(self):
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (0, {}))
        self.assertEqual(self.save(), 1)
        row = SyntheticQuestionnaireDraft.objects.get(application=self.draft)
        first = bytes(row.ciphertext)
        self.assertNotIn(b"4567890", first)
        self.assertNotIn(self.member.encode("ascii"), first)
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (1, self.answers))
        corrected = copy.deepcopy(self.answers)
        corrected["income"][0]["amount"] = 0
        self.assertEqual(self.save(1, answers=corrected), 2)
        row.refresh_from_db()
        self.assertNotEqual(first, bytes(row.ciphertext))
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (2, corrected))
        self.assertEqual(self.save(2, answers={}), 3)
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (3, {}))
        self.assertEqual(
            list(SyntheticQuestionnaireEvent.objects.order_by("revision").values_list(
                "revision", "actor_user_id",
            )), [(i, self.fixture["parent"].pk) for i in (1, 2, 3)],
        )
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_invalid_or_stale_values_cannot_mutate_snapshot(self):
        self.save()
        invalid = copy.deepcopy(self.answers)
        invalid["income"][0]["amount"] = True
        with self.assertRaisesRegex(QuestionnaireValidationError, "amount_type_invalid"):
            self.save(1, answers=invalid)
        invalid = copy.deepcopy(self.answers)
        invalid["income"][0]["contributor_id"] = str(uuid4())
        with self.assertRaisesRegex(QuestionnaireValidationError, "candidate_member_scope_denied"):
            self.save(1, answers=invalid)
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_sections_invalid"):
            self.save(1, answers={"consent": True})
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_revision_conflict"):
            self.save(0)
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (1, self.answers))
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 1)

    def test_shared_child_and_wrong_school_or_year_do_not_authorize_reads_or_writes(self):
        self.save()
        for changes in (
            {"user": self.separate_parent},
            {"user": self.fixture["director_a"]},
            {"user": self.fixture["operator"]},
            {"school_id": self.fixture["school_b"].pk},
            {"academic_year_id": self.fixture["year_b"].pk},
            {"household_id": self.separate.pk},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(Http404):
                    read_fictional_questionnaire(**self.scope(**changes))
                with self.assertRaises(Http404):
                    self.save(1, **changes)
        self.assertEqual(SyntheticQuestionnaireDraft.objects.count(), 1)
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 1)

    def test_revocation_blocks_existing_identity(self):
        self.save()
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.draft.school_id,
            household_id=self.draft.household_id, subject_user_id=self.fixture["parent"].pk,
        )
        with self.assertRaises(Http404):
            read_fictional_questionnaire(**self.scope())
        with self.assertRaises(Http404):
            self.save(1)
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 1)

    def test_wrong_key_cannot_read_or_overwrite(self):
        self.save()
        wrong = AESGCM.generate_key(bit_length=256)
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_integrity_failed"):
            read_fictional_questionnaire(**self.scope(key=wrong))
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_integrity_failed"):
            self.save(1, key=wrong)
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (1, self.answers))

    def test_ciphertext_cannot_be_replayed_in_another_household(self):
        self.save()
        source = SyntheticQuestionnaireDraft.objects.get(application=self.draft)
        SyntheticQuestionnaireDraft.objects.create(
            application=self.other_draft, revision=1, ciphertext=bytes(source.ciphertext),
        )
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_integrity_failed"):
            read_fictional_questionnaire(**self.scope(
                user=self.separate_parent, household_id=self.other_draft.household_id,
            ))

    def test_audit_failure_rolls_back_new_and_corrected_snapshots(self):
        with patch.object(SyntheticQuestionnaireEvent.objects, "create",
                          side_effect=RuntimeError("fictional audit failure")):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(SyntheticQuestionnaireDraft.objects.count(), 0)
        self.save()
        with patch.object(SyntheticQuestionnaireEvent.objects, "create",
                          side_effect=RuntimeError("fictional audit failure")):
            with self.assertRaises(RuntimeError):
                self.save(1, answers={})
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (1, self.answers))
        self.assertEqual(SyntheticQuestionnaireEvent.objects.count(), 1)

    def test_guard_and_event_instance_immutability(self):
        with override_settings(JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False):
            with self.assertRaises(PermissionDenied):
                self.save()
        with patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "jireh.runtime.settings"}):
            with self.assertRaises(PermissionDenied):
                self.save()
        with self.assertRaisesRegex(QuestionnaireValidationError, "questionnaire_key_invalid"):
            self.save(key=b"bad")
        self.save()
        event = SyntheticQuestionnaireEvent.objects.get()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    @skipUnless(connection.vendor == "postgresql", "Disposable PostgreSQL required")
    def test_database_guards_block_rebinding_revision_jumps_and_audit_mutation(self):
        self.save()
        row = SyntheticQuestionnaireDraft.objects.get()
        event = SyntheticQuestionnaireEvent.objects.get()
        for changes in ({"application_id": self.other_draft.pk, "revision": 2},
                        {"revision": 3}, {"revision": 2, "ciphertext": b"x"}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                SyntheticQuestionnaireDraft.objects.filter(pk=row.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticQuestionnaireEvent.objects.filter(pk=event.pk).update(revision=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticQuestionnaireEvent.objects.filter(pk=event.pk).delete()
        self.assertEqual(read_fictional_questionnaire(**self.scope()), (1, self.answers))
