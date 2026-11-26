"""Opt-in browser acceptance of the existing fixture-only financial profile."""
import base64
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.models import Student
from jireh.schools.operator_browser_acceptance import _database_readback, _https_server
from jireh.schools.saved_need_workspace import SavedNeedFixture
from jireh.schools.services import link_student_to_household
from . import test_customer_director_sessions as fixtures
from . import test_customer_financial_portal as financial
from .annual_school_plan import FICTIONAL_15145_PLAN
from .models import (
    AidApplication, FictionalNeedDecision, SyntheticAidOffer, SyntheticAidSubmission,
    SyntheticApplicationReview, SyntheticQuestionnaireDraft,
)
from .school_plan_revisions import record_fictional_school_plan
from .synthetic_document_views import _ALLOWED_FIXTURES


@override_settings(**financial.CustomerFinancialPortalTests._overridden_settings)
class AuthenticatedFinancialBrowserAcceptance(TransactionTestCase):
    """Use shared-memory test DB and real HTTPS sessions, not force_login."""

    def setUp(self):
        fixtures.DirectorSessionTests.setUp(self)
        self.scope = (self.school.pk, self.household.pk, self.year.pk)
        self.school.code = DEMO_SCHOOL_A_CODE
        self.school.save(update_fields=["code", "updated_at"])
        grades = []
        for grade in ("elementary", "middle"):
            child = Student.objects.create(
                school=self.school, first_name=grade.title(), last_name="Fictional",
            )
            link_student_to_household(
                school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk,
            )
            grades.append((child.pk, grade))
        # Seed the identical fictional school plan used by the case API tests.
        # Never enable rehearsal receipts or awards while the HTTP server runs.
        with self.settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=True):
            record_fictional_school_plan(
                user=self.actor, school_id=self.school.pk,
                academic_year_id=self.year.pk, plan=FICTIONAL_15145_PLAN,
            )
        self.enterContext(self.settings(
            JIREH_FINANCIAL_FIXTURE_SCOPES=(self.scope,),
            JIREH_SAVED_NEED_FIXTURE=SavedNeedFixture(
                self.school.pk, self.year.pk, self.household.pk, tuple(grades),
            ),
        ))

    def _family_login(self, page, expect):
        page.goto(fixtures.ORIGIN + "/customer/")
        form = page.locator("section").filter(has=page.get_by_role("heading", name="Family sign-in"))
        form.get_by_label("Username").fill(self.parent.username)
        form.get_by_label("Password").fill(fixtures.PASSWORD)
        form.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.get_by_role("heading", name="Your workspace")).to_be_visible(timeout=15000)

    def _director_login(self, context, page, expect, case_url):
        page.goto(fixtures.ORIGIN + "/customer/")
        form = page.locator("section").filter(
            has=page.get_by_role("heading", name="School director sign-in"),
        )
        form.get_by_label("School reference").fill(str(self.school.pk))
        form.get_by_label("Username").fill(self.actor.username)
        form.get_by_label("Password").fill(fixtures.PASSWORD)
        form.get_by_role("button", name="Continue to security key").click()
        expect(page.get_by_role("heading", name="Verify your security key")).to_be_visible(timeout=15000)
        self.assertEqual(page.goto(case_url).status, 403)
        page.goto(fixtures.ORIGIN + "/customer/")
        cdp = context.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        authenticator = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
            "protocol": "ctap2", "transport": "usb", "hasResidentKey": False,
            "hasUserVerification": True, "isUserVerified": True,
            "automaticPresenceSimulation": True,
        }})["authenticatorId"]
        private = self.key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cdp.send("WebAuthn.addCredential", {"authenticatorId": authenticator, "credential": {
            "credentialId": base64.b64encode(fixtures.CREDENTIAL_ID).decode(),
            "isResidentCredential": False, "rpId": fixtures.RP,
            "privateKey": base64.b64encode(private).decode(), "signCount": 0,
        }})
        page.get_by_role("button", name="Verify security key").click()
        expect(page.get_by_role("heading", name="Your workspace")).to_be_visible(timeout=15000)

    def _save_answers(self, page, expect):
        expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 0")
        for section, category in (("income", "EMPLOYMENT"), ("assets", "CASH"),
                                  ("liabilities", "MORTGAGE"), ("expenses", "HOUSING")):
            page.locator(f"#id_{section}-0-category").select_option(category)
            page.locator(f"#id_{section}-0-value").fill("40000.00" if section == "income" else "0.00")
            if section in ("income", "expenses"):
                page.locator(f"#id_{section}-0-period_start").fill("2026-01-01")
                page.locator(f"#id_{section}-0-period_end").fill(
                    "2026-12-31" if section == "income" else "2026-01-31",
                )
            else:
                page.locator(f"#id_{section}-0-as_of_date").fill("2026-06-30")
        page.get_by_role("button", name="Save fictional answers").click()
        expect(page.locator("#questionnaire-revision")).to_have_text("Saved revision: 1")
        page.reload()
        self.assertEqual(Decimal(page.locator("#id_income-0-value").input_value()), Decimal("40000.00"))

    def _review_family(self, page, expect, family_url, case_url):
        self._family_login(page, expect)
        self.assertEqual(page.goto(family_url).status, 200)
        for grade in ("Elementary", "Middle"):
            page.get_by_role("button", name=f"Include {grade}").click()
            expect(page.get_by_text(f"{1 if grade == 'Elementary' else 2} selected", exact=True)).to_be_visible()
        page.get_by_role("link", name="Open financial questionnaire").click()
        self._save_answers(page, expect)
        page.get_by_role("link", name="Return to annual application").click()
        page.get_by_role("link", name="Manage supporting documents").click()
        with page.expect_download() as sample:
            page.get_by_role("link", name="Original fictional PDF").click()
        path = sample.value.path()
        self.assertEqual(path.read_bytes(), _ALLOWED_FIXTURES[0])
        page.locator("#document-file").set_input_files(str(path))
        page.get_by_role("button", name="Save fictional document").click()
        expect(page.locator("#document-count")).to_have_text("1 listed")
        with page.expect_download() as saved:
            page.get_by_role("link", name="Download saved PDF").click()
        self.assertEqual(saved.value.path().read_bytes(), _ALLOWED_FIXTURES[0])
        page.get_by_role("link", name="Return to annual application").click()
        page.get_by_role("link", name="Review fictional application").click()
        expect(page.locator("#review-status")).to_have_text("Review required")
        page.get_by_role("checkbox", name="I reviewed this saved fictional application.").check()
        page.get_by_role("button", name="Confirm fictional review").click()
        expect(page.locator("#review-status")).to_have_text("Current fictional review confirmed")
        expect(page.locator("#submission-state")).to_have_text("Application state: DRAFT")
        expect(page.locator("#submission-readiness-status")).to_have_text("Final submission unavailable")
        self.assertEqual(page.goto(case_url).status, 403)
        page.goto(fixtures.ORIGIN + "/customer/")
        page.get_by_role("button", name="Sign out").click()
        expect(page.get_by_role("heading", name="Family sign-in")).to_be_visible(timeout=15000)

    def test_family_to_director(self):
        from playwright.sync_api import expect, sync_playwright

        family_url = fixtures.ORIGIN + reverse("jireh_workspace_family", args=self.scope)
        case_args = (self.school.pk, self.year.pk, self.draft.pk)
        case_url = fixtures.ORIGIN + reverse("jireh_customer_case", args=case_args)
        case_page = fixtures.ORIGIN + reverse("jireh_workspace_case", args=case_args)
        other = fixtures.ORIGIN + reverse(
            "jireh_workspace_director", args=(self.other_school.pk, self.other_year.pk),
        )
        with _https_server(fixtures.RP) as (port, pin, _), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=[
                "--no-proxy-server",
                f"--host-resolver-rules=MAP {fixtures.RP}:443 127.0.0.1:{port}, MAP * ~NOTFOUND",
                f"--ignore-certificate-errors-spki-list={pin}",
            ])
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", lambda route: route.continue_()
                              if route.request.url.startswith(fixtures.ORIGIN + "/") else route.abort())
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                self._review_family(page, expect, family_url, case_url)
                self.assertTrue(page.evaluate("window.isSecureContext"))
                self.assertEqual(_database_readback(lambda: SyntheticQuestionnaireDraft.objects.get(
                    application_id=self.draft.pk,
                ).revision), 1)
                self.assertEqual(_database_readback(SyntheticApplicationReview.objects.count), 1)
                self._director_login(context, page, expect, case_url)
                self.assertEqual(page.goto(case_page).status, 200)
                expect(page.locator("#case-child-count")).to_have_text("2")
                response = page.goto(case_url)
                self.assertEqual(response.status, 200)
                evidence = response.json()["financial_evidence"]
                self.assertEqual(evidence["questionnaire_revision"], 1)
                self.assertTrue(evidence["has_active_document_metadata"])
                self.assertTrue(evidence["has_confirmation_at_saved_revision"])
                self.assertEqual(evidence["need"]["status"], "available")
                self.assertEqual(evidence["need"]["unmet_tuition_cents"], 1_395_900)
                self.assertFalse(evidence["need"]["financial_verification_established"])
                self.assertEqual(evidence["combined_recommendation"], "unavailable")
                self.assertFalse(evidence["award_decision_available"])
                self.assertEqual(page.goto(other).status, 403)
                self.assertEqual(page.goto(family_url).status, 403)
                self.assertEqual(_database_readback(lambda: AidApplication.objects.values_list(
                    "status", flat=True,
                ).get(pk=self.draft.pk)), AidApplication.STATUS_DRAFT)
                for model in (FictionalNeedDecision, SyntheticAidOffer, SyntheticAidSubmission):
                    self.assertFalse(_database_readback(model.objects.exists))
                self.assertFalse(errors, errors)
                print("PASS: authenticated family financial browser, saved PDF and review, signed director case readback", flush=True)
            finally:
                browser.close()
