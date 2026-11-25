"""Director-facing read-only counts from scoped, fictional saved records."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import resolve, Resolver404, reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext

from jireh.financial_aid.models import (
    AidApplication, AidApplicationStudent, SyntheticAidSubmission, SyntheticAidOffer,
)
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.financial_aid.synthetic_submission import record_synthetic_demo_submission
from jireh.financial_aid.synthetic_offers import record_synthetic_officer_offer
from jireh.financial_aid.workload import WorkloadIntegrityError
from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import SchoolStaffAccess


_DEMO_TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True, "OPTIONS": {},
}]


@override_settings(
    ROOT_URLCONF="jireh.schools.demo_urls",
    TEMPLATES=_DEMO_TEMPLATES,
    JIREH_SYNTHETIC_SUBMISSION_ONLY=True,
)
class DirectorDatabaseTruthHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_synthetic_browser_demo()

    @staticmethod
    def url():
        return "/local-demo/director-summary/"

    def test_empty_authorized_school_is_truthful_zero_not_example_numbers(self):
        self.client.force_login(self.demo["director_a"])
        with CaptureQueriesContext(connection) as sql:
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertTrue(sql.captured_queries)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT")
                            for query in sql))
        body = response.content.decode()
        self.assertIn("Synthetic Christian Academy", body)
        self.assertIn("Draft household applications", body)
        self.assertIn("Fictional offered-aid records", body)
        self.assertIn("Not a live financial-aid report", body)
        self.assertIn('<div class="number">0</div>', body)
        self.assertIn('&#36;0.00', body)
        self.assertNotIn("Real awards: $", body)

    def test_database_backed_case_counts_and_fictional_offer_face_value(self):
        parent = self.demo["parent"]
        school = self.demo["school_a"]
        house = self.demo["household_a"]
        year = self.demo["year_a"]
        app = get_or_create_annual_draft(
            user=parent, school_id=school.pk, household_id=house.pk, academic_year_id=year.pk,
        )
        from jireh.schools.models import HouseholdStudent
        children = list(
            HouseholdStudent.objects.filter(household_id=house.pk)
            .order_by("student_id").values_list("student_id", flat=True)
        )
        self.assertEqual(len(children), 2)
        for child in children:
            select_student_for_draft(
                user=parent, school_id=school.pk, household_id=house.pk,
                academic_year_id=year.pk, student_id=child,
            )
        record_synthetic_demo_submission(
            user=parent, school_id=school.pk, household_id=house.pk,
            academic_year_id=year.pk, accuracy_attested=True,
        )
        record_synthetic_officer_offer(
            user=self.demo["director_a"], school_id=school.pk,
            academic_year_id=year.pk, application_id=app.pk, student_id=children[0],
        )

        before = (
            AidApplication.objects.count(), AidApplicationStudent.objects.count(),
            SyntheticAidSubmission.objects.count(), SyntheticAidOffer.objects.count(),
        )
        self.client.force_login(self.demo["director_a"])
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        page = response.content.decode()
        for expected in (
            '<div class="number">1</div>', '<div class="number">2</div>',
            '&#36;250.00', 'Test-only $250 need examples',
            'Not accepted, payable, or disbursed cash',
        ):
            self.assertIn(expected, page)
        self.assertEqual(before, (
            AidApplication.objects.count(), AidApplicationStudent.objects.count(),
            SyntheticAidSubmission.objects.count(), SyntheticAidOffer.objects.count(),
        ))
        app.refresh_from_db()
        self.assertEqual(app.status, "DRAFT")
        self.client.force_login(self.demo["director_b"])
        other_page = self.client.get(self.url())
        self.assertEqual(other_page.status_code, 200)
        self.assertIn('&#36;0.00', other_page.content.decode())
        self.assertNotIn('&#36;250.00', other_page.content.decode())
        self.assertNotIn(str(app.pk), other_page.content.decode())

    def test_unauthenticated_family_and_revoked_director_denied(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.force_login(self.demo["parent"])
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.demo["director_a"])
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        grant = SchoolStaffAccess.objects.get(user=self.demo["director_a"], school=self.demo["school_a"])
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        denied = self.client.get(self.url())
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("Synthetic Christian Academy", denied.content.decode())

    def test_disabled_runtime_and_untrusted_queries_fail_closed(self):
        self.client.force_login(self.demo["director_a"])
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.get(self.url() + "?school_id=other").status_code, 400)
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            self.assertEqual(self.client.get(self.url()).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(Resolver404):
                resolve(self.url())

    def test_planning_page_projects_without_writing_and_stays_within_school_scope(self):
        url = "/local-demo/director-planning/"
        self.assertEqual(self.client.get(url).status_code, 403)
        for actor in ("parent", "director_b"):
            self.client.force_login(self.demo[actor])
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.demo["director_a"])
        self.assertContains(self.client.get(self.url()), f'href="{url}"')
        with CaptureQueriesContext(connection) as sql:
            page = self.client.get(url, {"award": "2500.00", "category": "marketing"})
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in sql))
        self.assertIn("no-store", page["Cache-Control"])
        for value in ("15145", "65 open seats", "$24,825.00", "$21,325.00", "$247,500.00",
                      "Enrollment", "Fictional planning scenario"):
            self.assertContains(page, value)
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_planning_page_rejects_invalid_proposals_and_is_absent_from_runtime(self):
        self.client.force_login(self.demo["director_a"])
        url = "/local-demo/director-planning/"
        for query in ("?award=-1", "?award=3.001", "?award=999999.00&category=need",
                      "?award=1&award=2&category=need", "?award=1&category=unknown", "?school_id=2"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url + query).status_code, 400)
        self.assertEqual(self.client.post(url).status_code, 405)
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            self.assertEqual(self.client.get(url).status_code, 403)
        with override_settings(ROOT_URLCONF="jireh.runtime.urls"):
            with self.assertRaises(Resolver404):
                resolve(url)

    def test_planning_explains_regional_need_independently_of_proposed_aid(self):
        self.client.force_login(self.demo["director_a"])
        url = "/local-demo/director-planning/"
        for query in ({}, {"award": "2500.00", "category": "marketing"}):
            with self.subTest(query=query):
                page = self.client.get(url, query)
                for value in ("Regional tuition need", "FY 2027", "Pittsburgh", "$1,389.00",
                              "$20,268.00", "$23,825.00", "$9,866.00", "$13,959.00"):
                    self.assertContains(page, value)
                self.assertNotContains(page, "$14,959.00")

    def test_planning_fails_closed_when_regional_allowance_pin_changes(self):
        self.client.force_login(self.demo["director_a"])
        with patch("jireh.financial_aid.fictional_planning_need._ALLOWANCE_SHA256", "0" * 64):
            response = self.client.get("/local-demo/director-planning/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Regional need scenario unavailable."})

    def test_director_walkthrough_links_to_scoped_saved_summary(self):
        self.client.force_login(self.demo["director_a"])
        page = self.client.get("/local-demo/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="director-summary-link"')
        self.assertContains(page, 'href="/local-demo/director-summary/"')
        summary = self.client.get(self.url())
        self.assertEqual(summary.status_code, 200)
        self.assertContains(summary, "Director workload")
        self.assertContains(summary, "Synthetic Christian Academy")

    def test_integrity_failure_yields_unknown_not_zero(self):
        self.client.force_login(self.demo["director_a"])
        with patch("jireh.schools.demo_director_summary.summarize_draft_workload",
                   side_effect=WorkloadIntegrityError("fake private detail")):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("fake private detail", response.content.decode())
        self.assertNotIn('<div class="number">0</div>', response.content.decode())
