"""Exercise the real candidate URLConf without exposing it in the runtime."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent, AidAuditEvent
from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student
from jireh.schools.services import link_student_to_household


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_urls", JIREH_CUSTOMER_CORE_ACCEPTANCE=True,
    JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE=True,
    DEBUG=False, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False, JIREH_SYNTHETIC_SUBMISSION_ONLY=False,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=False, JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=False, JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class CustomerCoreRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.parent = user.objects.create_user(username="core-parent")
        cls.other_parent = user.objects.create_user(username="core-other-parent")
        cls.director = user.objects.create_user(username="core-director")
        cls.other_director = user.objects.create_user(username="core-other-director")
        cls.admin = user.objects.create_superuser(username="core-ungranted-admin")
        cls.school = School.objects.create(code="core-school-a", name="Fictional A")
        cls.other_school = School.objects.create(code="core-school-b", name="Fictional B")
        cls.year = AcademicYear.objects.create(school=cls.school, name="2026-27",
                                               start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        cls.other_year = AcademicYear.objects.create(school=cls.other_school, name="2026-27",
                                                     start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        cls.household = Household.objects.create(school=cls.school, name="Fictional family A")
        cls.separate = Household.objects.create(school=cls.school, name="Fictional separate household")
        cls.other_household = Household.objects.create(school=cls.other_school, name="Fictional family B")
        cls.child = Student.objects.create(school=cls.school, first_name="Fictional", last_name="Child")
        cls.other_child = Student.objects.create(school=cls.other_school, first_name="Fictional", last_name="Other")
        for household, student in ((cls.household, cls.child), (cls.separate, cls.child),
                                    (cls.other_household, cls.other_child)):
            link_student_to_household(school_id=household.school_id, household_id=household.pk, student_id=student.pk)
        HouseholdAccess.objects.create(household=cls.household, user=cls.parent)
        HouseholdAccess.objects.create(household=cls.separate, user=cls.other_parent)
        SchoolStaffAccess.objects.create(school=cls.school, user=cls.director, role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        SchoolStaffAccess.objects.create(school=cls.other_school, user=cls.other_director, role=SchoolStaffAccess.ROLE_AID_DIRECTOR)

    def client_for(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        return client

    def draft_url(self, school=None, household=None, year=None):
        return reverse("jireh_customer_draft", args=((school or self.school).pk,
                                                     (household or self.household).pk, (year or self.year).pk))

    def post(self, client, url):
        token = client.get(reverse("jireh_customer_csrf"), secure=True)
        self.assertEqual(token.status_code, 200)
        return client.post(url, secure=True, HTTP_ORIGIN="https://testserver",
                           HTTP_X_CSRFTOKEN=token.json()["csrf_token"])

    def counts(self):
        return (AidApplication.objects.count(), AidApplicationStudent.objects.count(), AidAuditEvent.objects.count())

    def test_authorized_draft_selection_and_director_readback(self):
        family = self.client_for(self.parent)
        draft_url = self.draft_url()
        self.assertEqual(family.get(draft_url, secure=True).status_code, 404)
        self.assertTrue(family.cookies["csrftoken"]["httponly"])
        self.assertTrue(family.cookies["csrftoken"]["secure"])
        self.assertEqual(family.post(draft_url, secure=True).status_code, 403)
        self.assertEqual(self.counts(), (0, 0, 0))
        draft = self.post(family, draft_url)
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.json()["status"], "DRAFT")
        self.assertIn("no-store", draft["Cache-Control"])
        self.assertEqual(draft["X-Frame-Options"], "DENY")
        self.assertEqual(draft["Referrer-Policy"], "no-referrer")
        self.assertEqual(draft["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.post(family, draft_url).json()["id"], draft.json()["id"])
        select = draft_url + f"students/{self.child.pk}/"
        self.assertEqual(self.post(family, select).status_code, 200)
        self.assertEqual(self.post(family, select).status_code, 200)
        self.assertEqual(AidApplicationStudent.objects.count(), 1)
        self.assertEqual(family.get(draft_url + "students/", secure=True).json()["student_ids"], [str(self.child.pk)])
        cases = reverse("jireh_customer_cases", args=(self.school.pk, self.year.pk))
        director = self.client_for(self.director)
        self.assertEqual(director.get(cases, secure=True).json()["applications"][0]["id"], draft.json()["id"])
        case = cases + draft.json()["id"] + "/"
        self.assertEqual(director.get(case, secure=True).json()["selected_student_ids"], [str(self.child.pk)])
        self.assertEqual(self.client_for(self.other_director).get(case, secure=True).status_code, 404)
        self.assertEqual(family.get(case, secure=True).status_code, 404)
        self.assertEqual(self.client_for(self.admin).get(case, secure=True).status_code, 404)
        self.assertEqual(director.get(cases, secure=True).status_code, 200)
        self.assertEqual(self.post(director, case).status_code, 405)
        self.assertEqual(AidApplication.objects.count(), 1)

    def test_cross_school_shared_child_wrong_year_revocation_and_forgery(self):
        family = self.client_for(self.parent)
        url = self.draft_url()
        family.get(url, secure=True)
        self.assertEqual(self.post(family, url).status_code, 200)
        before = self.counts()
        for denied in (self.draft_url(household=self.separate),
                       self.draft_url(school=self.other_school, household=self.other_household, year=self.other_year),
                       self.draft_url(year=self.other_year)):
            self.assertEqual(family.get(denied, secure=True, HTTP_X_SCHOOL_ID=str(self.school.pk)).status_code, 404)
            self.assertEqual(self.post(family, denied).status_code, 404)
        self.assertEqual(self.post(family, url + f"students/{self.other_child.pk}/").status_code, 404)
        self.assertEqual(self.client_for(self.other_parent).get(url, secure=True).status_code, 404)
        HouseholdAccess.objects.filter(user=self.parent, household=self.household).update(is_active=False)
        self.assertEqual(family.get(url, secure=True).status_code, 404)
        self.assertEqual(self.post(family, url).status_code, 404)
        self.assertEqual(self.counts(), before)

    def test_closed_by_default_tls_and_security_flags(self):
        family = self.client_for(self.parent)
        url = self.draft_url()
        self.assertEqual(family.get(url).status_code, 404)
        self.assertEqual(Client().get(url, secure=True).status_code, 403)
        for flag, value in (("JIREH_CUSTOMER_CORE_ACCEPTANCE", False), ("DEBUG", True),
                            ("CSRF_COOKIE_HTTPONLY", False), ("SESSION_COOKIE_SECURE", False),
                            ("SESSION_ENGINE", "django.contrib.sessions.backends.signed_cookies"),
                            ("JIREH_SYNTHETIC_SUBMISSION_ONLY", True), ("JIREH_SYNTHETIC_DOCUMENTS_ONLY", True),
                            ("JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", True), ("JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE", True)):
            with self.subTest(flag=flag), self.settings(**{flag: value}):
                self.assertEqual(family.get(url, secure=True).status_code, 404)
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(family.get(url, secure=True).status_code, 404)
        for excluded in ("/workspace/", "/test-auth/login/", "/local-demo/", "/admin/",
                         url + "synthetic/receipt/", url + "submit/", url + "pay/", url + "documents/"):
            self.assertEqual(family.get(excluded, secure=True).status_code, 404)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_masked_csrf_token_supports_httponly_cookie_and_rejects_foreign_origin(self):
        url = reverse("jireh_customer_csrf")
        self.assertEqual(Client().get(url, secure=True).status_code, 403)
        family = self.client_for(self.parent)
        response = family.get(url, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(family.cookies["csrftoken"]["httponly"])
        token = response.json()["csrf_token"]
        self.assertNotEqual(token, family.cookies["csrftoken"].value)
        for origin in ("https://untrusted.example", "null"):
            denied = family.post(self.draft_url(), secure=True, HTTP_ORIGIN=origin, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(family.post(self.draft_url(), secure=True, HTTP_ORIGIN="https://testserver",
                                     HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(family.post(url, secure=True, HTTP_ORIGIN="https://testserver",
                                     HTTP_X_CSRFTOKEN=token).status_code, 405)

    def test_database_error_is_generic_and_never_cached(self):
        family = self.client_for(self.parent)
        with patch("jireh.financial_aid.family_views.require_household_access",
                   side_effect=DatabaseError("secret database details")):
            response = family.get(self.draft_url(), secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Service unavailable."})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("secret", response.content.decode())
