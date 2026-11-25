"""Disposable application review HTTP and database acceptance."""
import json
import secrets
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import Client, TestCase, override_settings
from django.test.client import MULTIPART_CONTENT
from django.urls import reverse

from jireh.financial_aid import fictional_school_questions, synthetic_application_review
from jireh.financial_aid.document_lifecycle import create_synthetic_document, delete_synthetic_document
from jireh.financial_aid.models import (
    AidApplication, AidApplicationStudent, SyntheticAidOffer, SyntheticAidSubmission, SyntheticApplicationReview,
    SYNTHETIC_DISCLOSURE_VERSION,
)
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.financial_aid.synthetic_application_review import read_fictional_application_review
from jireh.financial_aid.synthetic_document_views import _ALLOWED_FIXTURES, _POLICY, _backend
from jireh.financial_aid.synthetic_questionnaire_storage import (
    FictionalQuestionnairePolicy, save_fictional_questionnaire,
)
from jireh.financial_aid.synthetic_submission_preflight import read_fictional_submission_preflight
from jireh.financial_aid.synthetic_submission import record_synthetic_demo_submission
from jireh.financial_aid.synthetic_offers import record_synthetic_officer_offer
from .demo_seed import seed_synthetic_browser_demo
from .grant_admin import revoke_household_access
from .models import HouseholdAccess, SchoolStaffAccess, Student


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=True,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=secrets.token_bytes(32),
    TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
    }],
)
class WorkspaceReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed_synthetic_browser_demo()
        cls.ids = dict(
            school_id=cls.fixture["school_a"].pk,
            household_id=cls.fixture["household_a"].pk,
            academic_year_id=cls.fixture["year_a"].pk,
        )
        cls.scope = dict(user=cls.fixture["parent"], **cls.ids)
        cls.draft = get_or_create_annual_draft(**cls.scope)
        cls.children = list(Student.objects.filter(school_id=cls.ids["school_id"]).order_by("first_name"))

    def setUp(self):
        from django.conf import settings
        self.key = settings.JIREH_SYNTHETIC_QUESTIONNAIRE_KEY
        self.member = str(uuid4())
        self.catalog = json.loads(
            (Path(__file__).resolve().parents[3] / "docs" / "questionnaire_v1_field_catalog.json")
            .read_text(encoding="utf-8")
        )
        self.policy = FictionalQuestionnairePolicy(
            reporting_year=2026, min_cents=0, max_cents=100000000,
            categories=(("EMPLOYMENT",), ("CASH",), ("MORTGAGE",), ("HOUSING",)),
            member_ids=(self.member,),
        )
        self.answers = {
            "income": [{"category": "EMPLOYMENT", "amount": 76543,
                        "period_start": "2026-01-01", "period_end": "2026-12-31",
                        "contributor_id": self.member}],
            "assets": [{"category": "CASH", "balance": 0, "as_of_date": "2026-06-30",
                        "owner_member_id": self.member}],
            "liabilities": [{"category": "MORTGAGE", "balance": 123456,
                             "as_of_date": "2026-06-30", "responsible_member_id": self.member}],
            "expenses": [{"category": "HOUSING", "amount": 98765,
                          "period_start": "2026-01-01", "period_end": "2026-01-31"}],
        }
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.fixture["parent"])
        self.url = reverse("jireh_workspace_review", kwargs=self.ids)
        self.client.get(self.url, secure=True)

    def save(self, revision=0):
        return save_fictional_questionnaire(
            **self.scope, expected_revision=revision, answers=self.answers,
            catalog=self.catalog, policy=self.policy, key=self.key,
        )

    def upload(self):
        return create_synthetic_document(
            **self.scope, request_key=str(uuid4()), category="FICTIONAL_TAX",
            data=_ALLOWED_FIXTURES[0], policy=_POLICY, backend=_backend(),
        )

    def prepare(self):
        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        self.save()
        return self.upload()

    def state(self):
        return read_fictional_application_review(**self.scope, key=self.key)

    def confirm(self, digest, *, reviewed="yes", csrf=True):
        headers = {"HTTP_ORIGIN": "https://testserver"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.client.cookies["csrftoken"].value
        return self.client.post(
            self.url, urlencode({"state_digest": digest, "reviewed": reviewed}),
            content_type="application/x-www-form-urlencoded",
            secure=True, **headers,
        )

    def test_confidential_contributor_request_is_idempotent_and_restricted(self):
        from .models import FictionalContributorException

        url = reverse("jireh_workspace_contributor_exception", kwargs=self.ids)
        token = self.client.cookies["csrftoken"].value

        def request(content=None, *, csrf=True):
            headers = {"HTTP_ORIGIN": "https://testserver"}
            if csrf:
                headers["HTTP_X_CSRFTOKEN"] = token
            body = urlencode({"csrfmiddlewaretoken": token}) if content is None and csrf else (content or "")
            return self.client.post(url, body, content_type="application/x-www-form-urlencoded",
                                    secure=True, **headers)

        self.assertEqual(request(csrf=False).status_code, 403)
        self.assertEqual(request("reason=private").status_code, 400)
        with override_settings(JIREH_SYNTHETIC_APPLICATION_REVIEW=False):
            self.assertEqual(request().status_code, 404)
        self.assertEqual(FictionalContributorException.objects.count(), 0)
        for _ in range(2):
            self.assertRedirects(request(), self.url, fetch_redirect_response=False)
        marker = FictionalContributorException.objects.get(application=self.draft)
        self.assertEqual(marker.requested_by_id, self.scope["user"].pk)
        self.assertContains(self.client.get(self.url, secure=True), "Additional review is pending.")
        self.assertIn("submission_additional_review_pending",
                      read_fictional_submission_preflight(**self.scope, key=self.key).blocking_codes)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        with self.assertRaisesMessage(ValidationError, "synthetic_additional_review_pending"):
            record_synthetic_demo_submission(**self.scope, accuracy_attested=True)
        self.assertFalse(SyntheticAidSubmission.objects.exists())
        with self.assertRaisesMessage(ValidationError, "synthetic_action_unavailable"):
            record_synthetic_officer_offer(user=self.fixture["director_a"], school_id=self.draft.school_id,
                academic_year_id=self.draft.academic_year_id, application_id=self.draft.pk,
                student_id=self.children[0].pk)

        case_url = reverse("jireh_workspace_case", kwargs={"school_id": self.draft.school_id,
            "academic_year_id": self.draft.academic_year_id, "application_id": self.draft.pk})
        ordinary = get_user_model().objects.create_user(username="fictional-ordinary-director")
        SchoolStaffAccess.objects.create(user=ordinary, school=self.draft.school,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        self.client.force_login(ordinary)
        self.assertNotContains(self.client.get(case_url, secure=True), "Additional review is pending.")
        reviewer = self.fixture["director_a"]
        reviewer.user_permissions.add(Permission.objects.get(content_type__app_label="schools",
            codename="view_fictionalcontributorexception"))
        self.client.force_login(reviewer)
        self.assertContains(self.client.get(case_url, secure=True), "Additional review is pending.")
        self.client.force_login(self.fixture["director_b"])
        self.assertEqual(self.client.get(case_url, secure=True).status_code, 404)

        other_household = self.fixture["household_b"]
        HouseholdAccess.objects.create(household=other_household, user=self.scope["user"])
        other_draft = get_or_create_annual_draft(user=self.scope["user"], school_id=other_household.school_id,
            household_id=other_household.pk, academic_year_id=self.fixture["year_b"].pk)
        FictionalContributorException.objects.create(application=other_draft, requested_by=self.scope["user"])
        other_reviewer = self.fixture["director_b"]
        other_reviewer.user_permissions.add(Permission.objects.get(content_type__app_label="schools",
            codename="view_fictionalcontributorexception"))
        self.assertContains(self.client.get(reverse("jireh_workspace_case", kwargs={"school_id": other_draft.school_id,
            "academic_year_id": other_draft.academic_year_id, "application_id": other_draft.pk}), secure=True),
            "Additional review is pending.")

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger evidence")
    def test_postgresql_contributor_review_marker_rejects_wrong_actor_and_rewrites(self):
        from .models import FictionalContributorException

        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FictionalContributorException.objects.create(application=self.draft, requested_by=self.fixture["director_b"])
        marker = FictionalContributorException.objects.create(application=self.draft, requested_by=self.scope["user"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            FictionalContributorException.objects.filter(pk=marker.pk).update(requested_by=self.fixture["director_b"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            FictionalContributorException.objects.filter(pk=marker.pk).delete()
        with self.assertRaisesMessage(IntegrityError, "Additional fictional review is pending"), transaction.atomic():
            SyntheticAidSubmission.objects.bulk_create([SyntheticAidSubmission(application=self.draft,
                actor_user=self.scope["user"], consent_version=SYNTHETIC_DISCLOSURE_VERSION, accuracy_attested=True)])

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger evidence")
    def test_postgresql_contributor_hold_rejects_raw_offer_after_historical_receipt(self):
        from .models import FictionalContributorException

        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        record_synthetic_demo_submission(**self.scope, accuracy_attested=True)
        FictionalContributorException.objects.create(application=self.draft, requested_by=self.scope["user"])
        selection = AidApplicationStudent.objects.get(application=self.draft)
        with self.assertRaisesMessage(IntegrityError, "Additional fictional review is pending"), transaction.atomic():
            SyntheticAidOffer.objects.bulk_create([SyntheticAidOffer(application=self.draft,
                student_selection=selection, actor_user=self.fixture["director_a"], bucket="need", amount_cents=25000)])
        self.assertTrue(SyntheticAidSubmission.objects.filter(application=self.draft).exists())
        director = self.fixture["director_a"]
        director.user_permissions.clear()
        self.client.force_login(director)
        page = self.client.get(reverse("jireh_workspace_case", kwargs={"school_id": self.draft.school_id,
            "academic_year_id": self.draft.academic_year_id, "application_id": self.draft.pk}), secure=True)
        self.assertContains(page, "A fictional offer is currently unavailable.")
        self.assertNotContains(page, "Private contributor review")
        self.assertNotContains(page, "Record fictional $250 need offer")

    def test_school_director_resolves_the_hold_and_family_sees_a_neutral_update(self):
        from .models import FictionalContributorDecision, FictionalContributorException

        marker = FictionalContributorException.objects.create(application=self.draft, requested_by=self.scope["user"])
        case_scope = {"school_id": self.draft.school_id, "academic_year_id": self.draft.academic_year_id,
                      "application_id": self.draft.pk}
        case_url = reverse("jireh_workspace_case", kwargs=case_scope)
        url = reverse("jireh_workspace_contributor_decision", kwargs=case_scope)
        token = self.client.cookies["csrftoken"].value

        def decide(decision="alternate_evidence_accepted", csrf=True):
            body = urlencode({"decision": decision, **({"csrfmiddlewaretoken": token} if csrf else {})})
            return self.client.post(url, body, secure=True, HTTP_ORIGIN="https://testserver",
                                    content_type="application/x-www-form-urlencoded")

        self.assertEqual(decide().status_code, 404)
        director = self.fixture["director_a"]
        self.client.force_login(director)
        permission = Permission.objects.get(content_type__app_label="schools", codename="view_fictionalcontributorexception")
        director.user_permissions.remove(permission)
        self.assertEqual(decide().status_code, 404)
        director.user_permissions.add(permission)
        self.client.force_login(self.fixture["director_b"])
        self.assertEqual(decide().status_code, 404)
        self.client.force_login(director)
        self.assertEqual(decide(csrf=False).status_code, 403)
        self.assertEqual(decide("private evidence").status_code, 400)
        for _ in range(2):
            self.assertRedirects(decide(), case_url, fetch_redirect_response=False)
        self.assertEqual(decide("contributor_exception_approved").status_code, 409)
        stored = FictionalContributorDecision.objects.get(marker=marker)
        self.assertEqual(stored.decided_by_id, director.pk)
        self.assertContains(self.client.get(case_url, secure=True), "Alternate evidence accepted")

        self.client.force_login(self.scope["user"])
        family_page = self.client.get(self.url, secure=True)
        self.assertContains(family_page, "Additional review completed.")
        self.assertNotContains(family_page, "Alternate evidence accepted")
        preflight = read_fictional_submission_preflight(**self.scope, key=self.key)
        self.assertNotIn("submission_additional_review_pending", preflight.blocking_codes)
        self.assertIn("submission_payment_unreconciled", preflight.blocking_codes)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger evidence")
    def test_postgresql_director_decision_requires_permission_and_releases_only_the_review_hold(self):
        from .models import FictionalContributorDecision, FictionalContributorException

        select_student_for_draft(**self.scope, student_id=self.children[0].pk)
        marker = FictionalContributorException.objects.create(application=self.draft, requested_by=self.scope["user"])
        permission = Permission.objects.get(content_type__app_label="schools", codename="view_fictionalcontributorexception")
        director = self.fixture["director_a"]
        director.user_permissions.remove(permission)
        other_director = self.fixture["director_b"]
        other_director.user_permissions.add(permission)
        outcome = FictionalContributorDecision.Outcome.CONTRIBUTOR_EXCEPTION
        for actor in (director, other_director, self.scope["user"]):
            with self.subTest(actor=actor.pk), self.assertRaisesMessage(IntegrityError, "Invalid contributor decision scope"), transaction.atomic():
                FictionalContributorDecision.objects.bulk_create([
                    FictionalContributorDecision(marker=marker, decided_by=actor, outcome=outcome),
                ])
        director.user_permissions.add(permission)
        decision = FictionalContributorDecision.objects.create(marker=marker, decided_by=director, outcome=outcome)
        with self.assertRaisesMessage(IntegrityError, "Contributor review decision is immutable"), transaction.atomic():
            FictionalContributorDecision.objects.filter(pk=decision.pk).update(
                outcome=FictionalContributorDecision.Outcome.ALTERNATE_EVIDENCE,
            )
        with self.assertRaisesMessage(IntegrityError, "Contributor review decision is immutable"), transaction.atomic():
            FictionalContributorDecision.objects.filter(pk=decision.pk).delete()
        receipt = record_synthetic_demo_submission(**self.scope, accuracy_attested=True)
        self.assertEqual(receipt.application_id, self.draft.pk)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_confirmation_rejects_multipart(self):
        self.prepare()
        response = self.client.post(
            self.url, {"state_digest": self.state()["digest"], "reviewed": "yes"},
            content_type=MULTIPART_CONTENT, secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertContains(response, "Explicit fictional review required.", status_code=400)
        self.assertFalse(SyntheticApplicationReview.objects.exists())

    def test_historical_school_answer_readback_and_question_only_invalidation(self):
        self.prepare()
        fixtures = fictional_school_questions._FIXTURES
        with patch.object(fictional_school_questions, "_FIXTURES", fixtures[:-1]):
            definitions = fictional_school_questions.school_questions_for_draft(self.draft, []).definitions
            worksheet = next(item for item in definitions if item.question_key == "example-worksheet")
            record = {"definition_id": str(worksheet.definition_id), "definition_version": "v1",
                      "answer": "Worksheet A"}
            self.answers["school_questions"] = [record]
            self.assertEqual(self.save(1), 2)
        digest = self.state()["digest"]
        self.assertEqual(self.confirm(digest).status_code, 302)
        self.assertContains(self.client.get(self.url, secure=True), "Worksheet A · v1")
        self.answers["school_questions"] = [{**record, "definition_version": "v2"}]
        with self.assertRaisesRegex(QuestionnaireValidationError, "^school_question_binding_invalid$"):
            self.save(2)
        self.answers["school_questions"] = [{**record, "definition_id": str(uuid4())}]
        with self.assertRaisesRegex(QuestionnaireValidationError, "^school_question_binding_invalid$"):
            self.save(2)
        self.assertEqual(self.state()["digest"], digest)
        self.answers["school_questions"] = [{**record, "answer": "Worksheet B"}]
        self.assertEqual(self.save(2), 3)
        self.assertEqual(self.confirm(digest).status_code, 409)
        self.assertContains(self.client.get(self.url, secure=True), "Worksheet B · v1")
        self.assertIsNone(self.state()["confirmation"])
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)

    def test_incomplete_explicit_confirmation_and_stale_digest(self):
        self.assertContains(self.client.get(self.url, secure=True), "Incomplete rehearsal")
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 400)
        self.prepare()
        digest = self.state()["digest"]
        self.assertContains(self.client.get(self.url, secure=True), "$55.00")
        self.assertEqual(self.confirm(digest, reviewed="no").status_code, 400)
        self.assertEqual(self.confirm(digest, csrf=False).status_code, 403)
        self.assertEqual(self.confirm("invalid").status_code, 409)
        self.assertEqual(self.confirm("é" * 64).status_code, 409)
        self.assertEqual(self.confirm(digest).status_code, 302)
        self.assertEqual(self.confirm(digest).status_code, 302)
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
        self.assertContains(self.client.get(self.url, secure=True), "Current fictional review confirmed")
        self.answers["income"][0]["amount"] = 76544
        self.save(1)
        self.assertEqual(self.confirm(digest).status_code, 409)
        self.assertContains(self.client.get(self.url, secure=True), "Review required")
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        self.assertEqual(SyntheticApplicationReview.objects.count(), 2)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_selection_and_document_changes_invalidate_confirmation(self):
        original = self.prepare()
        digest = self.state()["digest"]
        self.assertEqual(self.confirm(digest).status_code, 302)
        select_student_for_draft(**self.scope, student_id=self.children[1].pk)
        self.assertEqual(self.confirm(digest).status_code, 409)
        next_digest = self.state()["digest"]
        self.assertEqual(self.confirm(next_digest).status_code, 302)
        self.upload()
        self.assertEqual(self.confirm(next_digest).status_code, 409)
        current = self.state()["digest"]
        delete_synthetic_document(**self.scope, document_id=original.pk, backend=_backend())
        self.assertEqual(self.confirm(current).status_code, 409)
        self.assertIsNone(self.state()["confirmation"])

    def test_scope_revocation_and_closed_runtime(self):
        self.prepare()
        digest = self.state()["digest"]
        for who in ("director_a", "director_b", "operator"):
            other = Client()
            other.force_login(self.fixture[who])
            self.assertEqual(other.get(self.url, secure=True).status_code, 404)
        with override_settings(JIREH_SYNTHETIC_APPLICATION_REVIEW=False):
            self.assertEqual(self.client.get(self.url, secure=True).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.ids["school_id"],
            household_id=self.ids["household_id"], subject_user_id=self.fixture["parent"].pk,
        )
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        self.assertEqual(self.confirm(digest).status_code, 404)
        self.assertFalse(SyntheticApplicationReview.objects.exists())

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger acceptance")
    def test_postgresql_review_evidence_cannot_be_rewritten(self):
        self.prepare()
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        row = SyntheticApplicationReview.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticApplicationReview.objects.filter(pk=row.pk).update(state_digest="0" * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyntheticApplicationReview.objects.filter(pk=row.pk).delete()
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)

    def submission_preflight(self, **overrides):
        scope = {**self.scope, "key": self.key, **overrides}
        return read_fictional_submission_preflight(**scope)

    def test_submission_preflight_tracks_current_review_without_submitting(self):
        blocked = ("submission_disclosure_not_approved", "submission_payment_unreconciled")
        initial = self.submission_preflight()
        self.assertEqual(initial.application_id, self.draft.pk)
        self.assertEqual(initial.questionnaire_revision, 0)
        self.assertEqual(initial.blocking_codes, ("submission_review_incomplete", *blocked))

        self.prepare()
        self.assertEqual(
            self.submission_preflight().blocking_codes,
            ("submission_review_confirmation_required", *blocked),
        )
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        confirmed = self.submission_preflight()
        self.assertEqual(confirmed.questionnaire_revision, 1)
        self.assertEqual(confirmed.blocking_codes, blocked)
        self.assertEqual((confirmed.fee_amount_cents, confirmed.fee_currency), (5500, "USD"))

        self.answers["income"][0]["amount"] += 1
        self.save(1)
        corrected = self.submission_preflight()
        self.assertEqual(corrected.questionnaire_revision, 2)
        self.assertEqual(corrected.blocking_codes, ("submission_review_confirmation_required", *blocked))
        self.assertEqual(corrected.application_state, "DRAFT")
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "DRAFT")
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_submission_preflight_requires_current_actor_grant(self):
        self.prepare()
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        other_actor = type(self.scope["user"]).objects.create_user(username="fictional-second-reviewer")
        with self.assertRaises(Http404):
            self.submission_preflight(user=other_actor)
        HouseholdAccess.objects.create(household_id=self.ids["household_id"], user=other_actor)
        self.assertIn(
            "submission_review_confirmation_required",
            self.submission_preflight(user=other_actor).blocking_codes,
        )
        for scope in (
            {"school_id": self.fixture["school_b"].pk},
            {"academic_year_id": uuid4()},
            {"household_id": uuid4()},
        ):
            with self.subTest(scope=scope), self.assertRaises(Http404):
                self.submission_preflight(**scope)
        with override_settings(JIREH_SYNTHETIC_APPLICATION_REVIEW=False):
            with self.assertRaises(PermissionDenied):
                self.submission_preflight()
        revoke_household_access(
            actor=self.fixture["director_a"], school_id=self.ids["school_id"],
            household_id=self.ids["household_id"], subject_user_id=self.fixture["parent"].pk,
        )
        with self.assertRaises(Http404):
            self.submission_preflight()


    def test_submission_readiness_ui_uses_one_authorized_snapshot(self):
        initial = self.client.get(self.url, secure=True)
        self.assertContains(initial, 'data-submission-blocker="submission_review_incomplete"')
        self.assertContains(initial, "Application state: DRAFT")
        self.assertContains(initial, "Final submission unavailable")
        self.assertContains(initial, "$55.00 USD")
        self.prepare()
        with patch(
            "jireh.financial_aid.synthetic_application_review._review_state",
            wraps=synthetic_application_review._review_state,
        ) as read_state:
            pending = self.client.get(self.url, secure=True)
            self.assertEqual(read_state.call_count, 1)
        self.assertContains(pending, 'data-submission-blocker="submission_review_confirmation_required"')
        self.assertNotContains(pending, 'data-submission-blocker="submission_review_incomplete"')
        self.assertEqual(self.confirm(self.state()["digest"]).status_code, 302)
        current = self.client.get(self.url, secure=True)
        self.assertContains(current, "Reviewed financial revision: 1")
        self.assertContains(current, 'data-submission-blocker="submission_disclosure_not_approved"')
        self.assertContains(current, 'data-submission-blocker="submission_payment_unreconciled"')
        self.assertNotContains(current, 'data-submission-blocker="submission_review_confirmation_required"')
        self.assertNotContains(current, 'data-submission-blocker="submission_review_incomplete"')
        self.assertContains(current, "Final submission unavailable")
        self.answers["income"][0]["amount"] += 1
        self.save(1)
        changed = self.client.get(self.url, secure=True)
        self.assertContains(changed, "Reviewed financial revision: 2")
        self.assertContains(changed, 'data-submission-blocker="submission_review_confirmation_required"')
        self.assertContains(changed, 'data-submission-blocker="submission_payment_unreconciled"')
        self.assertContains(changed, "Final submission unavailable")
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AidApplication.STATUS_DRAFT)
        self.assertEqual(SyntheticApplicationReview.objects.count(), 1)
        self.assertFalse(SyntheticAidSubmission.objects.exists())
