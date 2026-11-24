"""Database acceptance for metadata-only fictional assessment evidence."""

from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import Household, HouseholdAccess, SchoolStaffAccess, Student
from jireh.schools.services import link_student_to_household

from .fictional_assessment_metadata import read_fictional_assessment_metadata
from .models import AidApplication, FinancialDocument, SyntheticQuestionnaireDraft
from .services import get_or_create_annual_draft, select_student_for_draft

class FictionalAssessmentMetadataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.school = cls.fixture["school_a"]
        cls.household = cls.fixture["household_a"]
        cls.director = cls.fixture["director_a"]
        cls.parent = cls.fixture["parent"]
        cls.scope = {"school_id": cls.school.pk, "academic_year_id": cls.fixture["year_a"].pk}
        cls.application = get_or_create_annual_draft(
            user=cls.parent, household_id=cls.household.pk, **cls.scope,
        )
        cls.child = Student.objects.get(school=cls.school, first_name="Jordan")

    def read(self, **overrides):
        arguments = {**self.scope, "user": self.director, "application_id": self.application.pk}
        return read_fictional_assessment_metadata(**(arguments | overrides))

    def document(self):
        return FinancialDocument.objects.create(
            school=self.school, household=self.household, application=self.application,
            created_by=self.parent, request_key=uuid4(), version=1, category="FICTIONAL_TAX",
            detected_media_type="application/pdf", byte_count=12, sha256="a" * 64,
        )

    def test_readback_selects_only_metadata_and_keeps_application_in_draft(self):
        empty = self.read()
        self.assertEqual(empty.application_id, self.application.pk)
        self.assertIsNone(empty.questionnaire_revision)
        self.assertFalse(empty.has_selected_student)
        self.assertFalse(empty.has_active_document_metadata)
        self.assertFalse(empty.has_pending_document_removal)

        SyntheticQuestionnaireDraft.objects.create(
            application=self.application, revision=1, ciphertext=b"opaque fictional bytes" * 3,
        )
        select_student_for_draft(
            user=self.parent, household_id=self.household.pk, student_id=self.child.pk, **self.scope,
        )
        document = self.document()
        with CaptureQueriesContext(connection) as queries:
            report = self.read()
        self.assertEqual(report.questionnaire_revision, 1)
        self.assertTrue(report.has_selected_student)
        self.assertTrue(report.has_active_document_metadata)
        self.assertFalse(report.has_pending_document_removal)
        for query in queries.captured_queries:
            sql = query["sql"].lower().strip()
            self.assertTrue(sql.startswith("select"))
            for forbidden in ("ciphertext", "sha256", "object_key", "request_key", "first_name"):
                self.assertNotIn(forbidden, sql)
        self.assertTrue(queries.captured_queries)
        self.assertFalse(hasattr(report, "assessment"))
        self.assertFalse(hasattr(report, "verified"))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, AidApplication.STATUS_DRAFT)

        document.state = FinancialDocument.STATE_DELETE_PENDING
        document.save(update_fields=["state", "updated_at"])
        pending = self.read()
        self.assertFalse(pending.has_active_document_metadata)
        self.assertTrue(pending.has_pending_document_removal)

    def test_student_link_to_another_household_does_not_supply_metadata(self):
        select_student_for_draft(
            user=self.parent, household_id=self.household.pk, student_id=self.child.pk, **self.scope,
        )
        self.document()
        another = Household.objects.create(school=self.school, name="Separate fictional household")
        HouseholdAccess.objects.create(household=another, user=self.parent)
        link_student_to_household(school_id=self.school.pk, household_id=another.pk, student_id=self.child.pk)
        draft = get_or_create_annual_draft(user=self.parent, household_id=another.pk, **self.scope)
        report = self.read(application_id=draft.pk)
        self.assertFalse(report.has_selected_student)
        self.assertFalse(report.has_active_document_metadata)

    def test_exact_school_year_application_and_persona_are_required(self):
        with self.assertRaises(PermissionDenied):
            self.read(user=AnonymousUser())
        for arguments in (
            {"user": self.parent}, {"user": self.fixture["director_b"]},
            {"school_id": self.fixture["school_b"].pk}, {"academic_year_id": self.fixture["year_b"].pk},
            {"application_id": uuid4()},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(Http404):
                self.read(**arguments)

    def test_current_grant_is_rechecked_in_the_metadata_query(self):
        grant = SchoolStaffAccess.objects.get(user=self.director)
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        with self.assertRaises(Http404):
            self.read()
        # Simulate revocation after the first authorization check returned.
        with patch("jireh.financial_aid.fictional_assessment_metadata.require_aid_director_access",
                   return_value=self.school), self.assertRaises(Http404):
            self.read()

    @override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False)
    def test_disabled_fixture_guard_prevents_metadata_read(self):
        with CaptureQueriesContext(connection) as queries, self.assertRaises(PermissionDenied):
            self.read()
        self.assertEqual(len(queries), 0)
