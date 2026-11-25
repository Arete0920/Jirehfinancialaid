"""End-to-end saved fictional need with actual encrypted questionnaire revisions."""
import copy
import json
import secrets
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import TestCase, override_settings

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import FictionalContributorException, HouseholdAccess, SchoolStaffAccess, Student

from .annual_school_plan import FICTIONAL_15145_PLAN, AnnualSchoolPlanError
from .assessment_contract import CandidateAssessmentError
from .hud_area_lookup import FictionalHudAddressGeography, FictionalHudAreaCrosswalk, FictionalHudAreaRow
from .hud_living_allowance import (
    FictionalHouseholdAllowanceRule, FictionalHudMonthlyRent, build_fictional_hud_living_allowance_table,
)
from .models import AidApplication, SyntheticAidOffer, SyntheticAidSubmission, SyntheticQuestionnaireDraft
from .questionnaire_validation import QuestionnaireValidationError
from .regional_need import FictionalRegionalNeedPolicy
from .saved_fictional_need import (
    FictionalChangedIncomeReview, SavedFictionalNeedContext, SavedFictionalNeedError, calculate_saved_fictional_need,
)
from .school_plan_revisions import record_fictional_school_plan
from .services import get_or_create_annual_draft, select_student_for_draft
from .synthetic_questionnaire_storage import FictionalQuestionnairePolicy, save_fictional_questionnaire


@override_settings(JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True)
class SavedFictionalNeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.family_scope = dict(
            user=cls.fixture["parent"], school_id=cls.fixture["school_a"].pk,
            household_id=cls.fixture["household_a"].pk, academic_year_id=cls.fixture["year_a"].pk,
        )
        cls.draft = get_or_create_annual_draft(**cls.family_scope)
        cls.children = tuple(Student.objects.filter(
            school_id=cls.family_scope["school_id"],
        ).order_by("pk").values_list("pk", flat=True))
        for child in cls.children:
            select_student_for_draft(**cls.family_scope, student_id=child)
        cls.plan_scope = dict(user=cls.fixture["director_a"], school_id=cls.draft.school_id,
                              academic_year_id=cls.draft.academic_year_id)
        record_fictional_school_plan(**cls.plan_scope, plan=FICTIONAL_15145_PLAN)

    def setUp(self):
        self.key = secrets.token_bytes(32)
        self.catalog = json.loads((Path(__file__).resolve().parents[3] / "docs" /
                                   "questionnaire_v1_field_catalog.json").read_text(encoding="utf-8"))
        member = str(uuid4())
        questionnaire_policy = FictionalQuestionnairePolicy(
            reporting_year=2026, min_cents=0, max_cents=100_000_000,
            categories=(("EMPLOYMENT",), ("CASH",), ("MORTGAGE",), ("HOUSING",)),
            member_ids=(member,),
        )
        self.answers = {
            "income": [{"category": "EMPLOYMENT", "amount": 4_000_000,
                        "period_start": "2026-01-01", "period_end": "2026-12-31", "contributor_id": member}],
            "assets": [{"category": "CASH", "balance": 0, "as_of_date": "2026-06-30", "owner_member_id": member}],
            "liabilities": [{"category": "MORTGAGE", "balance": 0, "as_of_date": "2026-06-30",
                             "responsible_member_id": member}],
            "expenses": [{"category": "HOUSING", "amount": 98765,
                          "period_start": "2026-01-01", "period_end": "2026-01-31"}],
        }
        # Same independently pinned FY 2027 Pittsburgh example as regional
        # planning PR #137; no runtime dependency on that open branch.
        version, area, geography = "fictional-15145-fy2027-v1", "METRO38300M38300", "4200399999"
        table = build_fictional_hud_living_allowance_table(
            dataset_version=version, hud_fiscal_year=2027,
            monthly_rents=(FictionalHudMonthlyRent(area, 2, 138_900),),
            household_rules=(FictionalHouseholdAllowanceRule(2, 2, 2, 360_000),),
        )
        self.context = SavedFictionalNeedContext(
            school_id=self.draft.school_id, academic_year_id=self.draft.academic_year_id,
            application_id=self.draft.pk, questionnaire_revision=1, plan_revision=1,
            grade_assignments=tuple(zip(self.children, ("elementary", "middle"))),
            adults=2, children=2, geography=FictionalHudAddressGeography("42003", True, geography),
            crosswalk=FictionalHudAreaCrosswalk(2027, (FictionalHudAreaRow(geography, area),)),
            crosswalk_sha256="9b23ab8b6f0c6c37c5e0bd12a3409c222ceaafedaee0117fa895f716c005269a",
            allowance_table=table,
            regional_policy=FictionalRegionalNeedPolicy(
                version, 2027, "10dc4f12ec5be0757c04de8237e9bb4c96d3a136ade0be55add75f2418d71fae",
                5_000, 0, "HALF_UP",
            ),
            questionnaire_policy=questionnaire_policy, balance_date=date(2026, 6, 30),
            scenario_committed_aid_cents=0, scenario_proposed_aid_cents=250_000,
        )

    def save(self, *, expected_revision=0, answers=None):
        return save_fictional_questionnaire(
            **self.family_scope, expected_revision=expected_revision,
            answers=self.answers if answers is None else answers,
            catalog=self.catalog, key=self.key, policy=self.context.questionnaire_policy,
        )

    def calculate(self, *, context=None, user=None, key=None):
        return calculate_saved_fictional_need(
            user=self.fixture["director_a"] if user is None else user,
            context=self.context if context is None else context,
            catalog=self.catalog, key=self.key if key is None else key,
        )

    def test_saved_income_drives_need_and_revision_bound_budget_projection(self):
        self.save()
        first = self.calculate()
        self.assertEqual(first.cost.net_tuition_cents, 2_382_500)
        self.assertEqual(first.regional_need.allowance_cents, 2_026_800)
        self.assertEqual(first.regional_need.expected_contribution_cents, 986_600)
        self.assertEqual(first.regional_need.unmet_tuition_cents, 1_395_900)
        self.assertEqual(first.projection.household_balance_cents, 2_232_500)
        self.assertEqual(first.projection.remaining_aid_budget_cents, 24_750_000)
        self.assertEqual(first.questionnaire_revision, 1)
        self.assertTrue(first.requires_school_authorization)
        self.assertFalse(first.financial_verification_established)
        changed = copy.deepcopy(self.answers)
        changed["income"][0]["amount"] = 5_000_000
        self.save(expected_revision=1, answers=changed)
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_questionnaire_revision_unavailable"):
            self.calculate()
        revised = replace(self.context, questionnaire_revision=2)
        self.assertEqual(self.calculate(context=revised).regional_need.unmet_tuition_cents, 895_900)
        record_fictional_school_plan(
            **self.plan_scope, plan=replace(FICTIONAL_15145_PLAN, annual_aid_budget_cents=28_000_000),
        )
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_plan_revision_unavailable"):
            self.calculate(context=revised)
        result = self.calculate(context=replace(revised, plan_revision=2))
        self.assertEqual(result.projection.remaining_aid_budget_cents, 27_750_000)
        self.assertEqual(result.plan_revision, 2)
        self.assertFalse(SyntheticAidOffer.objects.exists())
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_missing_partial_duplicate_and_unmatched_balance_evidence_denied(self):
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_questionnaire_revision_unavailable"):
            self.calculate()
        for revision, (section, update, error) in enumerate((
            ("income", [], "saved_need_financial_section_incomplete"),
            ("income", [{**self.answers["income"][0], "period_end": "2026-06-30"}],
             "saved_need_full_year_income_required"),
            ("income", self.answers["income"] * 2, "saved_need_ambiguous_financial_rows"),
            ("assets", [{**self.answers["assets"][0], "as_of_date": "2026-07-01"}],
             "saved_need_balance_date_mismatch"),
        ), start=1):
            with self.subTest(error=error):
                modified = {**self.answers, section: update}
                self.save(expected_revision=revision - 1, answers=modified)
                with self.assertRaisesRegex(SavedFictionalNeedError, error):
                    self.calculate(context=replace(self.context, questionnaire_revision=revision))

    def changed_income_context(self):
        baseline = self.calculate()
        review = FictionalChangedIncomeReview(
            evidence_id=uuid4(), reviewed_by_id=self.fixture["director_a"].pk,
            questionnaire_id=baseline.questionnaire_id, questionnaire_revision=baseline.questionnaire_revision,
            plan_id=baseline.plan_id, plan_revision=baseline.plan_revision,
            observed_from=date(2026, 9, 30), observed_through=date(2026, 10, 15),
            accepted_on=date(2026, 10, 20), reassess_on=date(2026, 12, 1),
            annual_income_cents=3_000_000, policy_version="fictional-job-loss-v1",
        )
        return replace(self.context, changed_income_review=review, assessment_date=date(2026, 11, 25))

    def test_reviewed_changed_income_recalculates_need_without_overwriting_baseline(self):
        self.save()
        saved = SyntheticQuestionnaireDraft.objects.get(application=self.draft)
        context = self.changed_income_context()
        result = self.calculate(context=context)
        self.assertEqual(result.regional_need.unmet_tuition_cents, 1_895_900)
        self.assertEqual(result.baseline_regional_need, self.calculate().regional_need)
        self.assertEqual(result.baseline_regional_need.unmet_tuition_cents, 1_395_900)
        self.assertEqual(result.changed_income_review, context.changed_income_review)
        self.assertEqual(result.projection, self.calculate().projection)
        self.assertFalse(result.financial_verification_established)
        self.assertFalse(SyntheticAidOffer.objects.exists())
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        saved.refresh_from_db()
        self.assertEqual(saved.revision, 1)
        self.assertEqual(saved.events.count(), 1)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_changed_income_rejects_stale_foreign_or_invalid_evidence(self):
        self.save()
        context = self.changed_income_context()
        review = context.changed_income_review
        for override, expected in (
            ({"questionnaire_id": uuid4()}, "saved_need_income_review_scope_mismatch"),
            ({"plan_revision": 2}, "saved_need_income_review_scope_mismatch"),
            ({"reviewed_by_id": self.fixture["director_b"].pk}, "saved_need_income_review_scope_mismatch"),
            ({"annual_income_cents": True}, "saved_need_income_review_invalid"),
            ({"policy_version": ""}, "saved_need_income_review_invalid"),
            ({"observed_through": date(2026, 10, 21)}, "saved_need_income_review_dates_invalid"),
        ):
            with self.subTest(override=override), self.assertRaisesRegex(SavedFictionalNeedError, expected):
                self.calculate(context=replace(context, changed_income_review=replace(review, **override)))
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_income_review_dates_invalid"):
            self.calculate(context=replace(context, assessment_date=review.reassess_on))
        corrected = copy.deepcopy(self.answers)
        corrected["income"][0]["amount"] += 100
        self.save(expected_revision=1, answers=corrected)
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_income_review_scope_mismatch"):
            self.calculate(context=replace(context, questionnaire_revision=2))

    def test_pending_contributor_review_blocks_changed_income_estimate(self):
        self.save()
        context = self.changed_income_context()
        FictionalContributorException.objects.create(application=self.draft, requested_by=self.fixture["parent"])
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_income_review_pending_contributor"):
            self.calculate(context=context)

    def test_scope_geography_policy_and_budget_fail_closed(self):
        self.save()
        for role in ("parent", "director_b", "operator"):
            with self.subTest(role=role), self.assertRaises(Http404):
                self.calculate(user=self.fixture[role])
        for context in (
            replace(self.context, academic_year_id=self.fixture["year_b"].pk),
            replace(self.context, application_id=uuid4()),
        ):
            with self.assertRaises(Http404):
                self.calculate(context=context)
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_grade_scope_mismatch"):
            self.calculate(context=replace(self.context, grade_assignments=((uuid4(), "middle"),)))
        with self.assertRaises(CandidateAssessmentError):
            self.calculate(context=replace(
                self.context, geography=replace(self.context.geography, address_verified=False),
            ))
        with self.assertRaises(CandidateAssessmentError):
            self.calculate(context=replace(self.context, crosswalk_sha256="0" * 64))
        with self.assertRaises(AnnualSchoolPlanError):
            self.calculate(context=replace(self.context, scenario_proposed_aid_cents=30_000_000))
        with self.assertRaises(QuestionnaireValidationError):
            self.calculate(key=secrets.token_bytes(32))
        with self.settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False), self.assertRaises(PermissionDenied):
            self.calculate()
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"), self.assertRaises(PermissionDenied):
            self.calculate()

    def test_source_grant_revocation_prevents_decryption_and_director_revocation_denies(self):
        self.save()
        grant = HouseholdAccess.objects.get(household_id=self.draft.household_id, user=self.fixture["parent"])
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        with self.assertRaisesRegex(SavedFictionalNeedError, "saved_need_source_grant_unavailable"):
            self.calculate()
        director = SchoolStaffAccess.objects.get(school_id=self.draft.school_id, user=self.fixture["director_a"])
        director.is_active = False
        director.save(update_fields=["is_active"])
        with self.assertRaises(Http404):
            self.calculate()
        self.assertEqual(SyntheticQuestionnaireDraft.objects.get(application=self.draft).revision, 1)
