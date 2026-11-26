"""Authenticated fixture-only questionnaire, PDF and review journey."""
import secrets
from urllib.parse import urlencode
from uuid import uuid4, uuid5

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import (
    AidApplication, FictionalNeedDecision, FinancialDocument, SyntheticAidSubmission, SyntheticApplicationReview,
    SyntheticPrepaymentHandoff, SyntheticQuestionnaireDraft, SyntheticQuestionnaireEvent,
)
from jireh.financial_aid.synthetic_document_views import _ALLOWED_FIXTURES
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE
from jireh.schools.saved_need_workspace import SavedNeedFixture
from jireh.schools.models import FictionalContributorException, Household, HouseholdAccess, Student
from jireh.schools.services import link_student_to_household
from .annual_school_plan import FICTIONAL_15145_PLAN
from .school_plan_revisions import record_fictional_school_plan
from . import test_customer_portal as portal
from . import test_customer_director_sessions as fixtures


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_financial_portal_urls", ALLOWED_HOSTS=[fixtures.RP, "testserver"],
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}],
    JIREH_CUSTOMER_FINANCIAL_ACCEPTANCE=True, JIREH_CUSTOMER_PORTAL_ACCEPTANCE=True,
    JIREH_CUSTOMER_CORE_ACCEPTANCE=True, JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE=True,
    JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE=True, JIREH_DIRECTOR_WEBAUTHN_RP_ID=fixtures.RP,
    JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE=False, JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=True,
    JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE=True, DEBUG=False, SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True, CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True,
    SECURE_SSL_REDIRECT=True, SESSION_ENGINE="django.contrib.sessions.backends.db",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False, JIREH_SYNTHETIC_SUBMISSION_ONLY=False,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=True, JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=True, JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=secrets.token_bytes(32),
    JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class CustomerFinancialPortalTests(TransactionTestCase):
    get = portal.CustomerPortalTests.get
    post = portal.CustomerPortalTests.post
    token = portal.CustomerPortalTests.token
    route = portal.CustomerPortalTests.route
    password = portal.CustomerPortalTests.password
    begin = portal.CustomerPortalTests.begin
    signed = portal.CustomerPortalTests.signed
    verified = portal.CustomerPortalTests.verified
    login_family = portal.CustomerPortalTests.login_family
    family = portal.CustomerPortalTests.family

    def setUp(self):
        portal.CustomerPortalTests.setUp(self)
        self.scope = (self.school.pk, self.household.pk, self.year.pk)
        self.other_household = Household.objects.create(school=self.other_school, name="Other fictional family")
        HouseholdAccess.objects.create(user=self.parent, household=self.other_household)
        self.other_scope = (self.other_school.pk, self.other_household.pk, self.other_year.pk)
        self.enterContext(self.settings(JIREH_FINANCIAL_FIXTURE_SCOPES=(self.scope,)))
        self.client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login_family(self.client).status_code, 200)

    def url(self, name, *extra, scope=None):
        return reverse("jireh_workspace_" + name, args=(*(scope or self.scope), *extra))

    def csrf(self, client=None):
        return self.get(client or self.client, reverse("jireh_customer_csrf")).json()["csrf_token"]

    def form(self, name, payload, *, client=None, csrf=True, scope=None):
        client = client or self.client
        headers = {"HTTP_HOST": fixtures.RP, "HTTP_ORIGIN": fixtures.ORIGIN}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.csrf(client)
            payload = {**payload, "csrfmiddlewaretoken": headers["HTTP_X_CSRFTOKEN"]}
        return client.post(self.url(name, scope=scope), urlencode(payload),
                           content_type="application/x-www-form-urlencoded", secure=True, **headers)

    def rows(self, revision=0, value="765.43"):
        member = str(uuid5(self.draft.pk, "fictional-contributor-v1"))
        fields = {"revision": revision}
        for section, category in (("income", "EMPLOYMENT"), ("assets", "CASH"),
                                  ("liabilities", "MORTGAGE"), ("expenses", "HOUSING")):
            fields.update({f"{section}-TOTAL_FORMS": 1, f"{section}-INITIAL_FORMS": int(revision > 0),
                           f"{section}-0-category": category, f"{section}-0-value": value})
            if section in ("income", "expenses"):
                fields.update({f"{section}-0-period_start": "2026-01-01",
                               f"{section}-0-period_end": "2026-01-31"})
            else:
                fields[f"{section}-0-as_of_date"] = "2026-01-31"
            if section != "expenses":
                fields[f"{section}-0-member"] = member
        return fields

    def upload(self, data, *, client=None, scope=None, csrf=True):
        client = client or self.client
        headers = {"HTTP_HOST": fixtures.RP, "HTTP_ORIGIN": fixtures.ORIGIN,
                   "HTTP_X_DOCUMENT_REQUEST_KEY": str(uuid4())}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.csrf(client)
        return client.post(self.url("document_upload", scope=scope), data=data,
                           content_type="application/pdf", secure=True, **headers)

    def test_authenticated_encrypted_financial_journey_stays_draft(self):
        page = self.get(self.client, self.family())
        self.assertContains(page, "Open financial questionnaire")
        self.assertContains(page, "Manage supporting documents")
        self.assertContains(page, "Review fictional application")
        child = Student.objects.create(school=self.school, first_name="Fictional", last_name="Child")
        link_student_to_household(school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk)
        selected = self.post(self.client, self.url("select", child.pk), {}, self.csrf())
        self.assertEqual(selected.status_code, 200)
        self.assertContains(self.get(self.client, self.url("questionnaire")), "Income")
        self.assertEqual(self.form("questionnaire", self.rows(), csrf=False).status_code, 403)
        result = self.form("questionnaire", self.rows())
        self.assertEqual(result.status_code, 302, result.content)
        row = SyntheticQuestionnaireDraft.objects.get(application=self.draft)
        self.assertEqual(row.revision, 1)
        self.assertNotIn(b"76543", bytes(row.ciphertext))
        self.assertEqual(SyntheticQuestionnaireEvent.objects.filter(questionnaire=row).count(), 1)
        self.assertContains(self.get(self.client, self.url("questionnaire")), "765.43")
        self.assertEqual(self.form("questionnaire", self.rows()).status_code, 409)
        self.assertEqual(self.upload(b"%PDF-1.4 arbitrary content").status_code, 400)
        self.assertEqual(self.upload(_ALLOWED_FIXTURES[0], csrf=False).status_code, 403)
        doc = self.upload(_ALLOWED_FIXTURES[0])
        self.assertEqual(doc.status_code, 200, doc.content)
        document_id = doc.json()["document_id"]
        self.assertEqual(self.get(self.client, self.url("document_read", document_id)).content, _ALLOWED_FIXTURES[0])
        self.assertContains(self.get(self.client, self.url("documents")), "1 listed")
        review = self.get(self.client, self.url("review"))
        self.assertContains(review, "Review required")
        self.assertContains(review, "$765.43")
        self.assertContains(review, "Final submission unavailable")
        self.assertContains(review, "$55.00")
        digest = review.context["review"]["digest"]
        self.assertEqual(self.form("review", {"state_digest": digest, "reviewed": "yes"}).status_code, 302)
        self.assertContains(self.get(self.client, self.url("review")), "Current fictional review confirmed")
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
        self.assertEqual(self.form("questionnaire", self.rows(1, "800.00")).status_code, 302)
        self.assertEqual(self.form("review", {"state_digest": digest, "reviewed": "yes"}).status_code, 409)
        self.assertContains(self.get(self.client, self.url("review")), "Review required")
        for _ in range(2):
            self.assertEqual(self.form("contributor_exception", {}).status_code, 302)
        self.assertEqual(FictionalContributorException.objects.count(), 1)
        self.assertContains(self.get(self.client, self.url("review")), "Additional review is pending")
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        self.assertEqual(self.get(self.client, self.url("review") + "rehearsal-receipt/").status_code, 404)

    def test_signed_decision_uses_current_handoff_and_preserves_draft(self):
        self.school.code = DEMO_SCHOOL_A_CODE
        self.school.save(update_fields=["code", "updated_at"])
        grades = []
        for grade in ("elementary", "middle"):
            child = Student.objects.create(school=self.school, first_name=grade.title(), last_name="Fictional")
            link_student_to_household(school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk)
            self.assertEqual(self.post(self.client, self.url("select", child.pk), {}, self.csrf()).status_code, 200)
            grades.append((child.pk, grade))
        with self.settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=True):
            record_fictional_school_plan(
                user=self.actor, school_id=self.school.pk, academic_year_id=self.year.pk, plan=FICTIONAL_15145_PLAN,
            )
        self.enterContext(self.settings(JIREH_SAVED_NEED_FIXTURE=SavedNeedFixture(
            self.school.pk, self.year.pk, self.household.pk, tuple(grades),
        )))
        answers = self.rows(value="0.00")
        answers.update({
            "income-0-value": "40000.00", "income-0-period_end": "2026-12-31",
            "assets-0-as_of_date": "2026-06-30", "liabilities-0-as_of_date": "2026-06-30",
        })
        self.assertEqual(self.form("questionnaire", answers).status_code, 302)
        self.assertEqual(self.upload(_ALLOWED_FIXTURES[0]).status_code, 200)
        digest = self.get(self.client, self.url("review")).context["review"]["digest"]
        self.assertEqual(self.form("review", {"state_digest": digest, "reviewed": "yes"}).status_code, 302)
        self.assertEqual(self.form("prepayment_handoff", {"state_digest": digest, "handed_off": "yes"}).status_code, 302)
        handoff = SyntheticPrepaymentHandoff.objects.get()
        director = Client(enforce_csrf_checks=True)
        self.verified(director)
        case_args = (self.school.pk, self.year.pk, self.draft.pk)
        case = reverse("jireh_workspace_case", args=case_args)
        payload = {
            "handoff": str(handoff.pk), "decision_revision": 0, "questionnaire_revision": 1,
            "plan_revision": 1, "amount": "250.00", "confirmed": "yes",
        }

        def post_decision(form=None, *, client=director, csrf=True, args=case_args):
            headers = {"HTTP_HOST": fixtures.RP, "HTTP_ORIGIN": fixtures.ORIGIN}
            if csrf:
                headers["HTTP_X_CSRFTOKEN"] = client.cookies[settings.CSRF_COOKIE_NAME].value
            return client.post(
                reverse("jireh_signed_need_decision", args=args), urlencode(form or payload),
                content_type="application/x-www-form-urlencoded", secure=True, **headers,
            )

        self.assertNotContains(self.get(director, case), "Record a fictional need decision")
        self.assertEqual(post_decision().status_code, 403)
        permission = Permission.objects.get(content_type__app_label="financial_aid", codename="add_fictionalneeddecision")
        self.actor.user_permissions.add(permission)
        self.assertContains(self.get(director, case), "Record a fictional need decision")
        unrelated = Permission.objects.get(content_type__app_label="auth", codename="change_user")
        self.actor.user_permissions.add(unrelated)
        self.assertEqual(self.get(director, case).status_code, 403)
        self.actor.user_permissions.remove(unrelated)
        self.assertEqual(post_decision(csrf=False).status_code, 403)
        self.assertEqual(post_decision(client=self.client).status_code, 403)
        self.assertEqual(post_decision(args=(self.other_school.pk, self.other_year.pk, self.draft.pk)).status_code, 403)
        self.assertEqual(post_decision({**payload, "handoff": str(uuid4())}).status_code, 409)
        self.assertEqual(post_decision({**payload, "amount": "50000.00"}).status_code, 409)
        for _ in range(2):
            response = post_decision()
            self.assertRedirects(response, case, fetch_redirect_response=False)
        row = FictionalNeedDecision.objects.get()
        self.assertEqual((row.revision, row.handoff_id, row.receipt_id, row.amount_cents),
                         (1, handoff.pk, None, 25_000))
        self.assertContains(self.get(self.client, self.family()), "$250.00")
        other_parent = get_user_model().objects.create_user(
            username="second-fictional-parent", password=fixtures.PASSWORD,
        )
        HouseholdAccess.objects.create(user=other_parent, household=self.household)
        other_family = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login_family(other_family, other_parent).status_code, 200)
        self.assertNotContains(self.get(other_family, self.family()), "$250.00")

        self.assertEqual(self.upload(_ALLOWED_FIXTURES[1]).status_code, 200)
        self.assertEqual(post_decision().status_code, 409)
        self.assertNotContains(self.get(self.client, self.family()), "$250.00")
        self.assertEqual(FictionalNeedDecision.objects.count(), 1)
        if connection.vendor == "postgresql":
            with self.assertRaises(IntegrityError), transaction.atomic():
                FictionalNeedDecision.objects.update(amount_cents=1)
            values = FictionalNeedDecision.objects.values(
                "application_id", "questionnaire_id", "questionnaire_revision", "plan_id", "actor_user_id",
                "amount_cents", "need_cents", "remaining_budget_cents", "calculation_version", "dataset_sha256",
            ).get()
            with self.assertRaises(IntegrityError), transaction.atomic():
                FictionalNeedDecision.objects.create(**values, revision=2)
        self.actor.user_permissions.remove(permission)
        self.assertEqual(post_decision().status_code, 403)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_separate_prepayment_handoff_tracks_the_exact_review(self):
        child = Student.objects.create(school=self.school, first_name="Fictional", last_name="Child")
        link_student_to_household(school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk)
        self.assertEqual(self.post(self.client, self.url("select", child.pk), {}, self.csrf()).status_code, 200)
        self.assertEqual(self.form("questionnaire", self.rows()).status_code, 302)
        self.assertEqual(self.upload(_ALLOWED_FIXTURES[0]).status_code, 200)

        current = self.get(self.client, self.url("review"))
        digest = current.context["review"]["digest"]
        payload = {"state_digest": digest, "handed_off": "yes"}
        director = Client(enforce_csrf_checks=True)
        self.verified(director)
        case = reverse("jireh_customer_case", args=(self.school.pk, self.year.pk, self.draft.pk))
        self.assertFalse(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])
        self.assertEqual(self.form("prepayment_handoff", payload).status_code, 409)
        self.assertEqual(self.form("review", {"state_digest": digest, "reviewed": "yes"}).status_code, 302)
        self.assertFalse(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])

        self.assertContains(self.get(self.client, self.url("review")), "Hand off confirmed draft")
        self.assertEqual(self.form("prepayment_handoff", payload, csrf=False).status_code, 403)
        self.assertEqual(self.form("prepayment_handoff", payload, client=director, csrf=False).status_code, 403)
        self.assertEqual(self.form("prepayment_handoff", payload).status_code, 302)
        self.assertEqual(self.form("prepayment_handoff", payload).status_code, 302)
        self.assertContains(self.get(self.client, self.url("review")), "Current draft handed off")
        self.assertTrue(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])
        self.assertEqual(SyntheticPrepaymentHandoff.objects.count(), 1)
        if connection.vendor == "postgresql":
            with self.assertRaises(IntegrityError), transaction.atomic():
                SyntheticPrepaymentHandoff.objects.update(confirmation_id=SyntheticApplicationReview.objects.get().pk)
            with self.assertRaises(IntegrityError), transaction.atomic():
                SyntheticPrepaymentHandoff.objects.all().delete()
        self.assertEqual(self.upload(_ALLOWED_FIXTURES[1]).status_code, 200)
        self.assertFalse(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])
        self.assertEqual(self.form("questionnaire", self.rows(1, "800.00")).status_code, 302)
        self.assertEqual(self.form("prepayment_handoff", payload).status_code, 409)
        self.assertFalse(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])

        new_digest = self.get(self.client, self.url("review")).context["review"]["digest"]
        self.assertEqual(self.form("review", {"state_digest": new_digest, "reviewed": "yes"}).status_code, 302)
        new_payload = {"state_digest": new_digest, "handed_off": "yes"}
        self.assertEqual(self.form("prepayment_handoff", new_payload).status_code, 302)
        self.assertEqual(SyntheticPrepaymentHandoff.objects.count(), 2)
        self.assertTrue(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])
        self.assertEqual(self.form("contributor_exception", {}).status_code, 302)
        self.assertEqual(self.form("prepayment_handoff", new_payload).status_code, 409)
        self.assertFalse(self.get(director, case).json()["financial_evidence"]["prepayment_handoff_current"])
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_exact_scope_roles_revocation_and_profile_boundaries(self):
        for name in ("questionnaire", "documents", "review"):
            self.assertEqual(self.get(self.client, self.url(name, scope=self.other_scope)).status_code, 404)
        other = get_user_model().objects.create_user(username="unmarked-family", password=fixtures.PASSWORD)
        HouseholdAccess.objects.create(user=other, household=self.household)
        unmarked = Client(enforce_csrf_checks=True)
        unmarked.force_login(other)
        self.assertEqual(self.get(unmarked, self.url("questionnaire")).status_code, 403)
        director = Client(enforce_csrf_checks=True)
        self.verified(director)
        self.assertEqual(self.get(director, self.url("review")).status_code, 403)
        for values in ({"JIREH_CUSTOMER_FINANCIAL_ACCEPTANCE": False},
                       {"JIREH_SYNTHETIC_SUBMISSION_ONLY": True},
                       {"JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE": True},
                       {"JIREH_FINANCIAL_FIXTURE_SCOPES": ()},
                       {"JIREH_SYNTHETIC_QUESTIONNAIRE_KEY": b"bad"},
                       {"ROOT_URLCONF": "jireh.runtime.customer_portal_urls"},
                       {"ROOT_URLCONF": "jireh.runtime.urls"}):
            url = self.url("questionnaire")
            with self.settings(**values):
                self.assertEqual(self.get(self.client, url).status_code, 404)
        HouseholdAccess.objects.filter(user=self.parent, household=self.household).update(is_active=False)
        self.assertEqual(self.get(self.client, self.url("questionnaire")).status_code, 404)
        self.assertFalse(SyntheticQuestionnaireDraft.objects.exists())
        self.assertFalse(FinancialDocument.objects.exists())
        self.assertFalse(SyntheticApplicationReview.objects.exists())
