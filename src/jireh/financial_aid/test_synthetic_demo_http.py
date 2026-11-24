"""Disposable real-session family -> aid director -> family HTTP acceptance.

No real application submissions, money grants, customer data or deployed APIs.
"""
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student,
)
from jireh.schools.services import link_student_to_household
from .models import SyntheticAidSubmission, SyntheticAidOffer
from .services import get_or_create_annual_draft, select_student_for_draft


class FictionalOfferHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(username="http-fictional-family")
        cls.director = User.objects.create_user(username="http-fictional-director")
        cls.other_director = User.objects.create_user(username="http-fictional-director-b")
        cls.school = School.objects.create(code="http-fictional-a", name="Fictional A")
        cls.other_school = School.objects.create(code="http-fictional-b", name="Fictional B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.house = Household.objects.create(school=cls.school, name="Fictional A House")
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Fictional B House",
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Fictional", last_name="Child"
        )
        cls.other_child = Student.objects.create(
            school=cls.other_school, first_name="Fictional", last_name="Other"
        )
        for house, child in ((cls.house, cls.child), (cls.other_house, cls.other_child)):
            link_student_to_household(
                school_id=house.school_id, household_id=house.pk, student_id=child.pk
            )
        HouseholdAccess.objects.create(household=cls.house, user=cls.parent)
        for director, school in (
            (cls.director, cls.school), (cls.other_director, cls.other_school)
        ):
            SchoolStaffAccess.objects.create(
                user=director, school=school, role=SchoolStaffAccess.ROLE_AID_DIRECTOR
            )

    def setUp(self):
        self.app = get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )

    def select_child(self):
        select_student_for_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )

    def client_as(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get(reverse("jireh_test_family_login"))
        self.assertIn("csrftoken", client.cookies)
        return client

    def url_receipt(self, *, school=None, household=None, year=None):
        return reverse("jireh_test_synthetic_receipt_create", kwargs={
            "school_id": school or self.school.pk,
            "household_id": household or self.house.pk,
            "academic_year_id": year or self.year.pk,
        })

    def url_read_receipt(self):
        return reverse("jireh_test_synthetic_receipt_read", kwargs={
            "school_id": self.school.pk,
            "household_id": self.house.pk,
            "academic_year_id": self.year.pk,
        })

    def url_family_offers(self, *, school=None, household=None, year=None):
        return reverse("jireh_test_synthetic_family_offers", kwargs={
            "school_id": school or self.school.pk,
            "household_id": household or self.house.pk,
            "academic_year_id": year or self.year.pk,
        })

    def url_director(self, *, school=None, year=None, student=None):
        return reverse("jireh_test_synthetic_officer_offer", kwargs={
            "school_id": school or self.school.pk,
            "academic_year_id": year or self.year.pk,
            "application_id": self.app.pk,
            "student_id": student or self.child.pk,
        })

    def post_attestation(self, client, data=None, *, csrf=True):
        payload = {"accuracy_attested": True} if data is None else data
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
        return client.post(
            self.url_receipt(), data=json.dumps(payload),
            content_type="application/json", **headers,
        )

    def post_officer(self, client, url=None, *, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
        return client.generic(
            "POST", url or self.url_director(), data=b"",
            content_type="application/octet-stream", **headers,
        )

    def test_full_family_to_officer_to_family_and_idempotent_retries(self):
        family = self.client_as(self.parent)
        self.select_child()
        initial = family.get(self.url_family_offers())
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json(), {"synthetic": True, "offers": []})
        first = self.post_attestation(family)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "SYNTHETIC_RECEIPT")
        self.assertEqual(self.post_attestation(family).json(), first.json())
        self.assertEqual(
            family.get(self.url_read_receipt()).json()["receipt_id"],
            first.json()["receipt_id"],
        )
        director = self.client_as(self.director)
        offer = self.post_officer(director)
        self.assertEqual(offer.status_code, 200, offer.content)
        self.assertEqual(offer.json()["amount_cents"], 25000)
        self.assertEqual(offer.json()["status"], "SYNTHETIC_OFFERED")
        self.assertEqual(self.post_officer(director).json(), offer.json())
        read = family.get(self.url_family_offers())
        self.assertEqual(read.status_code, 200)
        self.assertEqual(len(read.json()["offers"]), 1)
        self.assertEqual(read.json()["offers"][0]["amount_cents"], 25000)
        self.assertEqual(read.json()["offers"][0]["student_id"], str(self.child.pk))
        self.assertNotIn("actor_user", read.content.decode())
        self.assertNotIn("income", read.content.decode().lower())
        self.assertEqual(self.app.status, "DRAFT")
        self.assertEqual(SyntheticAidSubmission.objects.count(), 1)
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)

    def test_csrf_protected_post_and_explicit_fictional_attestation(self):
        family = self.client_as(self.parent)
        self.select_child()
        self.assertEqual(self.post_attestation(family, csrf=False).status_code, 403)
        for body in (
            {"accuracy_attested": False},
            {"accuracy_attested": None},
            {"accuracy_attested": "true"},
        ):
            response = self.post_attestation(family, body)
            self.assertEqual(response.status_code, 409)
        for body in (
            {"accuracy_attested": True, "amount_cents": 25000},
            {"consent_version": "synthetic-demo-v1"},
            [],
        ):
            response = self.post_attestation(family, body)
            self.assertEqual(response.status_code, 400)
        for raw in (
            '{"accuracy_attested":false,"accuracy_attested":true}',
            '{"accuracy_attested":true,"padding":"' + ("x" * 2048) + '"}',
        ):
            response = family.post(
                self.url_receipt(), data=raw, content_type="application/json",
                HTTP_X_CSRFTOKEN=family.cookies["csrftoken"].value,
            )
            self.assertEqual(response.status_code, 400)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_no_selected_child_disallows_synthetic_submission(self):
        family = self.client_as(self.parent)
        response = self.post_attestation(family)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_officer_cannot_create_offer_before_receipt_or_without_csrf(self):
        director = self.client_as(self.director)
        self.select_child()
        self.assertEqual(self.post_officer(director, csrf=False).status_code, 403)
        self.assertEqual(self.post_officer(director).status_code, 409)
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_cross_school_read_and_write_fail_without_side_effect(self):
        family = self.client_as(self.parent)
        self.select_child()
        for url in (
            self.url_receipt(school=self.other_school.pk),
            self.url_receipt(household=self.other_house.pk),
            self.url_receipt(year=self.other_year.pk),
        ):
            result = family.post(
                url, data=json.dumps({"accuracy_attested": True}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=family.cookies["csrftoken"].value,
            )
            self.assertEqual(result.status_code, 404)
        for url in (
            self.url_family_offers(school=self.other_school.pk),
            self.url_family_offers(household=self.other_house.pk),
            self.url_family_offers(year=self.other_year.pk),
        ):
            self.assertEqual(family.get(url).status_code, 404)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

        self.assertEqual(self.post_attestation(family).status_code, 200)
        foreign = self.client_as(self.other_director)
        self.assertEqual(self.post_officer(foreign).status_code, 404)
        director = self.client_as(self.director)
        self.assertEqual(
            self.post_officer(director, self.url_director(school=self.other_school.pk)).status_code,
            404,
        )
        self.assertEqual(
            self.post_officer(director, self.url_director(student=self.other_child.pk)).status_code,
            404,
        )
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_revoked_household_and_staff_grants_denied(self):
        family = self.client_as(self.parent)
        self.select_child()
        self.assertEqual(self.post_attestation(family).status_code, 200)
        director = self.client_as(self.director)
        SchoolStaffAccess.objects.filter(
            school=self.school, user=self.director
        ).update(is_active=False)
        self.assertEqual(self.post_officer(director).status_code, 404)
        self.assertFalse(SyntheticAidOffer.objects.exists())
        HouseholdAccess.objects.filter(
            household=self.house, user=self.parent
        ).update(is_active=False)
        self.assertEqual(family.get(self.url_family_offers()).status_code, 404)
        self.assertEqual(family.get(self.url_read_receipt()).status_code, 404)
