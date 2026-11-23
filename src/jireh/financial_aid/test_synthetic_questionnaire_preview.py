"""School-grant and no-storage acceptance for CROWN fixed-fictional preview."""

import copy
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import TestCase, override_settings

from jireh.financial_aid.models import AidApplication, AidAuditEvent
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.services import get_or_create_annual_draft
from jireh.financial_aid.synthetic_questionnaire_preview import (
    preview_fictional_financial_structure,
)
from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, Student,
)
from jireh.schools.services import link_student_to_household


CATALOG_FILE = (
    Path(__file__).resolve().parents[3] / "docs"
    / "questionnaire_v1_field_catalog.json"
)


class FictionalQuestionnairePreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent_a = User.objects.create_user(username="preview-parent-a")
        cls.parent_separate = User.objects.create_user(username="preview-parent-separate")
        cls.parent_b = User.objects.create_user(username="preview-parent-b")
        cls.school_a = School.objects.create(code="preview-school-a", name="Fictional A")
        cls.school_b = School.objects.create(code="preview-school-b", name="Fictional B")
        cls.year_a = AcademicYear.objects.create(
            school=cls.school_a, name="2026-27", start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.year_b = AcademicYear.objects.create(
            school=cls.school_b, name="2026-27", start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
        )
        cls.house_a = Household.objects.create(school=cls.school_a, name="Private A")
        cls.house_separate = Household.objects.create(
            school=cls.school_a, name="Private Separate",
        )
        cls.house_b = Household.objects.create(school=cls.school_b, name="Private B")
        for house, person in (
            (cls.house_a, cls.parent_a),
            (cls.house_separate, cls.parent_separate),
            (cls.house_b, cls.parent_b),
        ):
            HouseholdAccess.objects.create(household=house, user=person)
        shared = Student.objects.create(
            school=cls.school_a, first_name="Shared", last_name="Fictional",
        )
        link_student_to_household(
            school_id=cls.school_a.pk, household_id=cls.house_a.pk,
            student_id=shared.pk,
        )
        link_student_to_household(
            school_id=cls.school_a.pk, household_id=cls.house_separate.pk,
            student_id=shared.pk,
        )
        for person, school, house, year in (
            (cls.parent_a, cls.school_a, cls.house_a, cls.year_a),
            (cls.parent_separate, cls.school_a, cls.house_separate, cls.year_a),
            (cls.parent_b, cls.school_b, cls.house_b, cls.year_b),
        ):
            get_or_create_annual_draft(
                user=person, school_id=school.pk, household_id=house.pk,
                academic_year_id=year.pk,
            )

    @staticmethod
    def catalog():
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))

    def preview(self, **overrides):
        options = {
            "user": self.parent_a, "school_id": self.school_a.pk,
            "household_id": self.house_a.pk, "academic_year_id": self.year_a.pk,
            "scenario_id": "fictional_modest", "catalog": self.catalog(),
        }
        options.update(overrides)
        return preview_fictional_financial_structure(**options)

    def test_both_crown_fictional_cases_validate_without_any_mutation(self):
        before = (AidApplication.objects.count(), AidAuditEvent.objects.count())
        for case in ("fictional_modest", "fictional_moderate"):
            with self.subTest(case=case):
                response = self.preview(scenario_id=case)
                self.assertEqual(response, {
                    "scenario_id": case, "demo_only": True,
                    "validated_candidate_sections": ["income", "assets", "liabilities"],
                    "full_questionnaire_complete": False,
                    "financial_answers_stored": False,
                    "consent_captured": False,
                    "assessment_or_award_performed": False,
                })
                self.assertNotIn("4800000", str(response))
                self.assertNotIn("8200000", str(response))
                self.assertNotIn("Private", str(response))
                self.assertNotIn("11111111", str(response))
        self.assertEqual(
            (AidApplication.objects.count(), AidAuditEvent.objects.count()), before
        )

    def test_cross_school_and_separated_households_never_share_grants(self):
        for changed in (
            {"user": self.parent_b},
            {"user": self.parent_separate},
            {"school_id": self.school_b.pk},
            {"household_id": self.house_separate.pk},
            {"academic_year_id": self.year_b.pk},
            {"school_id": uuid4()},
        ):
            with self.subTest(changed=changed), self.assertRaises(Http404):
                self.preview(**changed)
        self.assertTrue(self.preview()["demo_only"])
        self.assertTrue(self.preview(
            user=self.parent_separate, household_id=self.house_separate.pk
        )["demo_only"])

    def test_anonymous_disabled_school_and_revoked_grant_are_denied(self):
        with self.assertRaises(PermissionDenied):
            self.preview(user=AnonymousUser())
        HouseholdAccess.objects.filter(
            user=self.parent_a, household=self.house_a
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self.preview()
        HouseholdAccess.objects.filter(
            user=self.parent_a, household=self.house_a
        ).update(is_active=True)
        School.objects.filter(pk=self.school_a.pk).update(is_active=False)
        with self.assertRaises(Http404):
            self.preview()

    def test_no_preview_in_runtime_or_without_synthetic_settings(self):
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(PermissionDenied):
                self.preview()
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            with self.assertRaises(PermissionDenied):
                self.preview()

    def test_no_unknown_scenario_and_catalog_drift_rejected(self):
        for code in (None, "real_customer", "fictional_modest ", 1, {}):
            with self.subTest(code=code), self.assertRaisesRegex(
                QuestionnaireValidationError, "^synthetic_scenario_unavailable$"
            ):
                self.preview(scenario_id=code)
        unsafe = copy.deepcopy(self.catalog())
        unsafe["requirements"]["no_data_storage"] = False
        with self.assertRaisesRegex(
            QuestionnaireValidationError, "^candidate_catalog_not_approved_for_design$"
        ):
            self.preview(catalog=unsafe)
