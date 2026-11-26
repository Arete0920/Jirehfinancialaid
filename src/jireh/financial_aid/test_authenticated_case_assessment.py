"""Signed director sessions read the same saved evidence without creating awards."""
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.models import Household, HouseholdAccess, Student
from jireh.schools.saved_need_workspace import SavedNeedFixture
from jireh.schools.services import link_student_to_household
from . import test_customer_financial_portal as financial
from . import test_customer_director_sessions as fixtures
from .annual_school_plan import FICTIONAL_15145_PLAN
from .models import AidApplication, FictionalNeedDecision, SyntheticAidOffer, SyntheticAidSubmission
from .school_plan_revisions import record_fictional_school_plan
from .services import get_or_create_annual_draft
from .synthetic_document_views import _ALLOWED_FIXTURES


@override_settings(**financial.CustomerFinancialPortalTests._overridden_settings)
class AuthenticatedCaseAssessmentTests(TransactionTestCase):
    setUp = financial.CustomerFinancialPortalTests.setUp
    get = financial.CustomerFinancialPortalTests.get
    post = financial.CustomerFinancialPortalTests.post
    token = financial.CustomerFinancialPortalTests.token
    route = financial.CustomerFinancialPortalTests.route
    password = financial.CustomerFinancialPortalTests.password
    begin = financial.CustomerFinancialPortalTests.begin
    signed = financial.CustomerFinancialPortalTests.signed
    verified = financial.CustomerFinancialPortalTests.verified
    login_family = financial.CustomerFinancialPortalTests.login_family
    family = financial.CustomerFinancialPortalTests.family
    url = financial.CustomerFinancialPortalTests.url
    csrf = financial.CustomerFinancialPortalTests.csrf
    form = financial.CustomerFinancialPortalTests.form
    rows = financial.CustomerFinancialPortalTests.rows
    upload = financial.CustomerFinancialPortalTests.upload

    def case_url(self, application=None):
        row = application or self.draft
        return reverse("jireh_customer_case", args=(row.school_id, row.academic_year_id, row.pk))

    def case_page_url(self, application=None):
        row = application or self.draft
        return reverse("jireh_workspace_case", args=(row.school_id, row.academic_year_id, row.pk))

    def assert_read_only_case(self, director):
        page = self.get(director, self.case_page_url())
        self.assertContains(page, "Saved fictional evidence")
        self.assertContains(page, "Combined recommendation unavailable")
        self.assertContains(page, "Award decision unavailable")
        for text in ("Record fictional need decision", "Record fictional $250 need offer",
                     "Project fictional need aid", "Record contributor decision",
                     "Record fictional income evidence"):
            self.assertNotContains(page, text)
        self.assertIn("no-store", page["Cache-Control"])
        return page

    def evidence(self, client):
        response = self.get(client, self.case_url())
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["financial_evidence"]

    def test_role_scope_and_actual_revision_metadata(self):
        director = Client(enforce_csrf_checks=True)
        self.assertEqual(self.password(director).status_code, 200)
        self.assertEqual(self.get(director, self.case_url()).status_code, 403)
        self.assertEqual(self.get(director, self.case_page_url()).status_code, 403)
        challenge = self.begin(director)
        self.assertEqual(self.post(director, self.route("complete"), self.signed(challenge), self.token(director)).status_code, 200)
        initial = self.evidence(director)
        self.assertIsNone(initial["questionnaire_revision"])
        self.assertEqual(initial["need"], {"status": "unavailable"})
        self.assertFalse(initial["award_decision_available"])
        page = self.assert_read_only_case(director)
        self.assertContains(page, "Saved questionnaire revision: None")
        self.assertContains(page, "Saved-evidence calculation unavailable.")
        self.assertNotContains(page, 'id="saved-need-unmet"')
        self.assertEqual(self.get(self.client, self.case_url()).status_code, 403)
        self.assertEqual(self.get(self.client, self.case_page_url()).status_code, 403)
        self.assertEqual(self.form("questionnaire", self.rows()).status_code, 302)
        after = self.evidence(director)
        self.assertEqual(after["questionnaire_revision"], 1)
        self.assertNotIn("765.43", str(after))
        page = self.assert_read_only_case(director)
        self.assertContains(page, "Saved questionnaire revision: 1")
        self.assertNotContains(page, "765.43")
        other = Household.objects.create(school=self.school, name="Unlisted fixture")
        HouseholdAccess.objects.create(user=self.parent, household=other)
        draft = get_or_create_annual_draft(user=self.parent, school_id=self.school.pk,
                                            household_id=other.pk, academic_year_id=self.year.pk)
        response = self.get(director, self.case_url(draft))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("financial_evidence", response.json())
        self.assertNotContains(self.get(director, self.case_page_url(draft)), "Saved fictional evidence")
        with self.settings(ROOT_URLCONF="jireh.runtime.customer_portal_urls"):
            self.assertNotContains(self.get(director, self.case_page_url()), "Saved fictional evidence")
        self.grant.is_active = False
        self.grant.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.get(director, self.case_url()).status_code, 403)
        self.assertEqual(self.get(director, self.case_page_url()).status_code, 403)

    def test_actual_saved_need_updates_and_contributor_hold_blocks_estimate(self):
        self.school.code = DEMO_SCHOOL_A_CODE
        self.school.save(update_fields=["code", "updated_at"])
        grades = []
        for grade in ("elementary", "middle"):
            child = Student.objects.create(school=self.school, first_name="Fictional", last_name=grade)
            link_student_to_household(school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk)
            self.assertEqual(self.post(self.client, self.url("select", child.pk), {}, self.csrf()).status_code, 200)
            grades.append((child.pk, grade))
        # Only fixture setup can seed the validated school plan. Never enable
        # the legacy receipt/award profile during an HTTP request.
        with self.settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=True):
            record_fictional_school_plan(user=self.actor, school_id=self.school.pk,
                                        academic_year_id=self.year.pk, plan=FICTIONAL_15145_PLAN)
        self.enterContext(self.settings(JIREH_SAVED_NEED_FIXTURE=SavedNeedFixture(
            self.school.pk, self.year.pk, self.household.pk, tuple(grades),
        )))
        answers = self.rows(value="0.00")
        answers.update({"income-0-value": "40000.00", "income-0-period_end": "2026-12-31",
                        "assets-0-as_of_date": "2026-06-30", "liabilities-0-as_of_date": "2026-06-30"})
        self.assertEqual(self.form("questionnaire", answers).status_code, 302)
        self.assertEqual(self.upload(_ALLOWED_FIXTURES[0]).status_code, 200)
        review = self.get(self.client, self.url("review"))
        self.assertEqual(self.form("review", {
            "state_digest": review.context["review"]["digest"], "reviewed": "yes",
        }).status_code, 302)
        director = Client(enforce_csrf_checks=True)
        self.verified(director)
        before = self.evidence(director)["need"]
        self.assertEqual(before["status"], "available", before)
        self.assertEqual(before["net_tuition_cents"], 2_382_500)
        self.assertEqual(before["unmet_tuition_cents"], 1_395_900)
        self.assertFalse(before["financial_verification_established"])
        self.assertTrue(before["requires_school_authorization"])
        page = self.assert_read_only_case(director)
        self.assertContains(page, "$13,959.00")
        self.assertContains(page, "$23,825.00")
        self.assertContains(page, "Supporting document metadata present")
        self.assertContains(page, "Historical confirmation at saved revision")
        self.assertNotContains(page, "40000.00")
        answers["revision"] = 1
        for section in ("income", "assets", "liabilities", "expenses"):
            answers[f"{section}-INITIAL_FORMS"] = 1
        answers["income-0-value"] = "50000.00"
        self.assertEqual(self.form("questionnaire", answers).status_code, 302)
        after = self.evidence(director)["need"]
        self.assertEqual(after["questionnaire_revision"], 2)
        self.assertEqual(after["unmet_tuition_cents"], 895_900)
        page = self.assert_read_only_case(director)
        self.assertContains(page, "$8,959.00")
        self.assertContains(page, "Historical confirmation at an earlier revision")
        self.assertNotContains(page, "$13,959.00")
        self.assertEqual(self.form("contributor_exception", {}).status_code, 302)
        held = self.evidence(director)
        self.assertTrue(held["contributor_review_pending"])
        self.assertEqual(held["need"], {"status": "held"})
        self.assertEqual(held["combined_recommendation"], "unavailable")
        self.assertFalse(held["award_decision_available"])
        page = self.assert_read_only_case(director)
        self.assertContains(page, "Additional contributor review is pending.")
        self.assertNotContains(page, 'id="saved-need-unmet"')
        self.assertNotContains(page, "$8,959.00")
        self.assertFalse(FictionalNeedDecision.objects.exists())
        self.assertFalse(SyntheticAidOffer.objects.exists())
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
