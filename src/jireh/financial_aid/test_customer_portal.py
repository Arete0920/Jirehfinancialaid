"""Exercise real signed session routes and the reused HTML workspace together."""
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import AidApplication
from jireh.schools.invitations import issue_household_invitation
from jireh.schools.models import HouseholdAccess, Student
from jireh.schools.redemption import issue_mailbox_challenge
from jireh.schools.services import link_student_to_household
from . import test_customer_director_sessions as fixtures


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_portal_urls", ALLOWED_HOSTS=[fixtures.RP, "testserver"],
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}],
    JIREH_CUSTOMER_PORTAL_ACCEPTANCE=True, JIREH_CUSTOMER_CORE_ACCEPTANCE=True,
    JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE=True, JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE=True,
    JIREH_DIRECTOR_WEBAUTHN_RP_ID=fixtures.RP, JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE=False,
    JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=True, JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE=True,
    DEBUG=False, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db", JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False,
    JIREH_SYNTHETIC_SUBMISSION_ONLY=False, JIREH_SYNTHETIC_DOCUMENTS_ONLY=False,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False, JIREH_SYNTHETIC_APPLICATION_REVIEW=False,
    JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class CustomerPortalTests(TransactionTestCase):
    # Share the already certified fictional identity and cryptographic fixtures;
    # do not inherit or rerun their unrelated test methods.
    setUp = fixtures.DirectorSessionTests.setUp
    route = fixtures.DirectorSessionTests.route
    cases = fixtures.DirectorSessionTests.cases
    get = fixtures.DirectorSessionTests.get
    token = fixtures.DirectorSessionTests.token
    post = fixtures.DirectorSessionTests.post
    password = fixtures.DirectorSessionTests.password
    begin = fixtures.DirectorSessionTests.begin
    signed = fixtures.DirectorSessionTests.signed
    verified = fixtures.DirectorSessionTests.verified

    def home(self, client):
        return self.get(client, reverse("jireh_workspace"))

    def family(self):
        return reverse("jireh_workspace_family", args=(self.school.pk, self.household.pk, self.year.pk))

    def director(self, school=None, year=None):
        return reverse("jireh_workspace_director", args=((school or self.school).pk, (year or self.year).pk))

    def login_family(self, client, account=None, *, onboarding=False):
        url = reverse("jireh_customer_onboarding_login" if onboarding else "jireh_customer_family_login")
        return self.post(client, url, {"username": (account or self.parent).username,
                                       "password": fixtures.PASSWORD}, self.get(client, url).json()["csrf_token"])

    def test_family_reuses_existing_pages_and_guarded_mutations(self):
        client = Client(enforce_csrf_checks=True)
        landing = self.home(client)
        self.assertContains(landing, "Family sign-in")
        self.assertIn("frame-ancestors 'none'", landing["Content-Security-Policy"])
        self.assertIn("no-store", landing["Cache-Control"])
        self.assertEqual(self.get(client, self.family()).status_code, 403)
        self.assertEqual(self.login_family(client).status_code, 200)
        self.assertContains(self.home(client), "Family applications")
        self.assertNotContains(self.home(client), "Fictional B")
        page = self.get(client, self.family())
        self.assertContains(page, "DRAFT — saved")
        self.assertNotContains(page, "Open financial questionnaire")
        self.assertNotContains(page, "Manage supporting documents")
        self.assertEqual(self.get(client, self.director()).status_code, 403)
        child = Student.objects.create(school=self.school, first_name="Fictional", last_name="Child")
        link_student_to_household(school_id=self.school.pk, household_id=self.household.pk, student_id=child.pk)
        args = (self.school.pk, self.household.pk, self.year.pk, child.pk)
        mutation = reverse("jireh_workspace_select", args=args)
        self.assertEqual(mutation, reverse("jireh_customer_select", args=args))
        self.assertContains(self.get(client, self.family()), mutation)
        token = self.get(client, reverse("jireh_customer_csrf")).json()["csrf_token"]
        self.assertEqual(self.post(client, mutation, {}, token).status_code, 200)
        self.assertContains(self.get(client, self.family()), "1 selected")
        HouseholdAccess.objects.filter(user=self.parent).update(is_active=False)
        self.assertEqual(self.get(client, self.family()).status_code, 403)
        self.assertNotContains(self.home(client), "Fictional family")
        self.assertEqual(self.post(client, reverse("jireh_workspace_logout"), {}, token).status_code, 200)

    def test_director_requires_mfa_and_reads_same_saved_draft(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.password(client).status_code, 200)
        pending = self.home(client)
        self.assertContains(pending, "Verify your security key")
        self.assertContains(pending, self.digest)
        self.assertNotContains(pending, "Fictional family")
        self.assertEqual(self.get(client, self.director()).status_code, 403)
        challenge = self.begin(client)
        result = self.post(client, self.route("complete"), self.signed(challenge), self.token(client))
        self.assertEqual(result.status_code, 200)
        self.assertContains(self.home(client), "School director")
        self.assertNotContains(self.home(client), "Fictional B")
        self.assertEqual(self.get(client, self.family()).status_code, 403)
        self.assertEqual(self.get(client, self.director(self.other_school, self.other_year)).status_code, 403)
        page = self.get(client, self.director())
        self.assertContains(page, "Director workload")
        self.assertContains(page, self.draft.pk)
        case = reverse("jireh_workspace_case", args=(self.school.pk, self.year.pk, self.draft.pk))
        self.assertContains(page, case)
        self.assertContains(self.get(client, case), "Selected children")
        self.assertNotContains(self.get(client, case), "Record fictional")
        self.grant.is_active = False
        self.grant.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.get(client, case).status_code, 403)

    def test_invitation_only_session_has_no_family_data_before_new_login(self):
        from django.contrib.auth import get_user_model
        new = get_user_model().objects.create_user(username="portal-new", password=fixtures.PASSWORD)
        _, invite = issue_household_invitation(actor=self.actor, school_id=self.school.pk,
                                               household_id=self.household.pk, email="fictional@example.invalid")
        _, mailbox = issue_mailbox_challenge(user=new, email="fictional@example.invalid")
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login_family(client, new, onboarding=True).status_code, 200)
        page = self.home(client)
        self.assertContains(page, "Redeem your first household invitation")
        self.assertNotContains(page, "Fictional family")
        self.assertEqual(self.get(client, self.family()).status_code, 403)
        redeem = reverse("jireh_customer_onboarding_redeem", args=(self.school.pk, self.household.pk))
        token = self.get(client, reverse("jireh_customer_onboarding_login")).json()["csrf_token"]
        self.assertEqual(self.post(client, redeem, {"invitation_token": invite, "mailbox_token": mailbox}, token).status_code, 200)
        self.assertContains(self.home(client), "Family sign-in")
        self.assertEqual(self.get(client, self.family()).status_code, 403)
        self.assertEqual(self.login_family(client, new).status_code, 200)
        self.assertContains(self.get(client, self.family()), "DRAFT — saved")
        self.assertEqual(AidApplication.objects.count(), 1)

    def test_closed_runtime_and_unmarked_session_cannot_render_customer_data(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse("jireh_workspace")
        for values in ({"JIREH_CUSTOMER_PORTAL_ACCEPTANCE": False}, {"JIREH_CUSTOMER_CORE_ACCEPTANCE": False},
                       {"CSRF_COOKIE_HTTPONLY": False}, {"JIREH_SYNTHETIC_DOCUMENTS_ONLY": True},
                       {"SETTINGS_MODULE": "jireh.runtime.settings"}, {"ROOT_URLCONF": "jireh.runtime.urls"}):
            with self.settings(**values):
                self.assertEqual(self.get(client, url).status_code, 404)
        self.assertEqual(client.get(url, HTTP_HOST=fixtures.RP).status_code, 404)
        for user in (self.parent, self.actor, self.admin):
            client.force_login(user)
            self.assertContains(self.home(client), "no eligible customer access")
            self.assertEqual(self.get(client, self.family()).status_code, 403)
            self.assertEqual(self.get(client, self.director()).status_code, 403)
            household = reverse("jireh_customer_household", args=(self.school.pk, self.household.pk))
            self.assertEqual(self.get(client, household).status_code, 403)
