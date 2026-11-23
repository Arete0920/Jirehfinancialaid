"""Fictional officer $250 offer and family readback; no live aid awards."""
from datetime import date
from queue import Queue
from threading import Thread

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings

from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student,
)
from jireh.schools.services import link_student_to_household
from .models import (
    AidApplication, AidApplicationStudent,
    SyntheticAidOffer, SyntheticAidSubmission,
)
from .services import get_or_create_annual_draft, select_student_for_draft
from .synthetic_submission import record_synthetic_demo_submission
from .synthetic_offers import record_synthetic_officer_offer, read_synthetic_family_offers


class SyntheticOfficerOfferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(username="fictional-offer-parent")
        cls.other_parent = User.objects.create_user(username="fictional-offer-other-parent")
        cls.officer = User.objects.create_user(username="fictional-offer-director")
        cls.other_officer = User.objects.create_user(username="fictional-offer-other-director")
        cls.admin = User.objects.create_superuser(
            username="fictional-offer-ungranted-admin",
            email="admin@example.invalid", password="synthetic-only",
        )
        cls.school = School.objects.create(code="offer-school-a", name="Fictional A")
        cls.other_school = School.objects.create(code="offer-school-b", name="Fictional B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.house = Household.objects.create(school=cls.school, name="Synthetic House A")
        cls.other_house = Household.objects.create(
            school=cls.other_school, name="Synthetic House B",
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Synthetic", last_name="Child A",
        )
        cls.other_child = Student.objects.create(
            school=cls.other_school, first_name="Synthetic", last_name="Child B",
        )
        for house, child in ((cls.house, cls.child), (cls.other_house, cls.other_child)):
            link_student_to_household(
                school_id=house.school_id, household_id=house.pk, student_id=child.pk
            )
        for user, house in ((cls.parent, cls.house), (cls.other_parent, cls.other_house)):
            HouseholdAccess.objects.create(household=house, user=user)
        for user, school in (
            (cls.officer, cls.school), (cls.other_officer, cls.other_school)
        ):
            SchoolStaffAccess.objects.create(
                school=school, user=user, role=SchoolStaffAccess.ROLE_AID_DIRECTOR
            )

    def fixture(self):
        application = get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )
        select_student_for_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )
        return application

    def submit(self):
        return record_synthetic_demo_submission(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            accuracy_attested=True,
        )

    def offer(self, **overrides):
        kwargs = dict(
            user=self.officer, school_id=self.school.pk,
            academic_year_id=self.year.pk,
            application_id=self.app.pk, student_id=self.child.pk,
        )
        kwargs.update(overrides)
        return record_synthetic_officer_offer(**kwargs)

    def test_fictional_250_offer_one_row_and_authorized_family_readback(self):
        self.app = self.fixture()
        self.submit()
        first = self.offer()
        retry = self.offer()
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(first.actor_user_id, self.officer.pk)
        self.assertEqual(first.application_id, self.app.pk)
        self.assertEqual(first.bucket, "need")
        self.assertEqual(first.amount_cents, 25000)
        self.assertIsNotNone(first.created_at)
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "DRAFT")
        result = read_synthetic_family_offers(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].amount_cents, 25000)
        self.assertEqual(result[0].student_id, str(self.child.pk))
        self.assertEqual(result[0].status, "SYNTHETIC_OFFERED")
        self.assertNotIn("25000", repr(result[0]))
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            first.delete()

    def test_no_officer_offer_before_fictional_receipt(self):
        self.app = self.fixture()
        with self.assertRaises(ValidationError):
            self.offer()
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_director_must_hold_exact_school_grant(self):
        self.app = self.fixture()
        self.submit()
        for person, scope in (
            (self.parent, self.school),
            (self.admin, self.school),
            (self.other_officer, self.school),
            (self.officer, self.other_school),
        ):
            with self.subTest(person=person.username, school=scope.code):
                with self.assertRaises((Http404, PermissionDenied)):
                    self.offer(user=person, school_id=scope.pk)
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_wrong_year_and_unselected_child_never_create_an_offer(self):
        self.app = self.fixture()
        self.submit()
        for kw in (
            {"academic_year_id": self.other_year.pk},
            {"student_id": self.other_child.pk},
        ):
            with self.subTest(kw=kw):
                with self.assertRaises(Http404):
                    self.offer(**kw)
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_family_readback_is_school_and_household_private(self):
        self.app = self.fixture()
        self.submit()
        self.offer()
        for kw in (
            {"user": self.other_parent},
            {"school_id": self.other_school.pk},
            {"household_id": self.other_house.pk},
            {"academic_year_id": self.other_year.pk},
        ):
            params = dict(
                user=self.parent, school_id=self.school.pk,
                household_id=self.house.pk, academic_year_id=self.year.pk,
            )
            params.update(kw)
            with self.subTest(kw=kw):
                with self.assertRaises((Http404, PermissionDenied)):
                    read_synthetic_family_offers(**params)
        HouseholdAccess.objects.filter(
            household=self.house, user=self.parent
        ).update(is_active=False)
        with self.assertRaises(Http404):
            read_synthetic_family_offers(
                user=self.parent, school_id=self.school.pk,
                household_id=self.house.pk, academic_year_id=self.year.pk,
            )
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)

    def test_revoked_director_grant_blocks_new_offer(self):
        self.app = self.fixture()
        self.submit()
        SchoolStaffAccess.objects.filter(
            school=self.school, user=self.officer
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self.offer()
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_synthetic_switch_disabled_prevents_offer_and_readback(self):
        self.app = self.fixture()
        self.submit()
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            with self.assertRaises(PermissionDenied):
                self.offer()
            with self.assertRaises(PermissionDenied):
                read_synthetic_family_offers(
                    user=self.parent, school_id=self.school.pk,
                    household_id=self.house.pk, academic_year_id=self.year.pk,
                )
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_constraints_reject_any_other_amount_or_bucket(self):
        self.app = self.fixture()
        self.submit()
        offer = self.offer()
        for update in ({"amount_cents": 24999}, {"bucket": "marketing"}):
            with self.subTest(update=update):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        SyntheticAidOffer.objects.filter(pk=offer.pk).update(**update)
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)


class SyntheticOfficerPostgresTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Disposable PostgreSQL required")
        User = get_user_model()
        self.parent = User.objects.create_user(username="pg-fictional-offer-parent")
        self.officer = User.objects.create_user(username="pg-fictional-offer-officer")
        self.school = School.objects.create(code="pg-fictional-offer", name="PG Fictional")
        self.year = AcademicYear.objects.create(
            school=self.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        self.house = Household.objects.create(school=self.school, name="PG Fictional Family")
        HouseholdAccess.objects.create(household=self.house, user=self.parent)
        SchoolStaffAccess.objects.create(
            school=self.school, user=self.officer,
            role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        )
        self.child = Student.objects.create(
            school=self.school, first_name="PG", last_name="Child"
        )
        link_student_to_household(
            school_id=self.school.pk, household_id=self.house.pk, student_id=self.child.pk,
        )
        self.app = get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
        )
        self.selected = select_student_for_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )
        record_synthetic_demo_submission(
            user=self.parent, school_id=self.school.pk,
            household_id=self.house.pk, academic_year_id=self.year.pk,
            accuracy_attested=True,
        )

    def offer(self):
        return record_synthetic_officer_offer(
            user=self.officer, school_id=self.school.pk,
            academic_year_id=self.year.pk, application_id=self.app.pk,
            student_id=self.child.pk,
        )

    def test_raw_bulk_offer_cannot_cross_application_or_bypass_actor_grant(self):
        for actor in (self.parent,):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SyntheticAidOffer.objects.bulk_create([
                        SyntheticAidOffer(
                            application=self.app, student_selection=self.selected,
                            actor_user=actor, bucket="need", amount_cents=25000,
                        )
                    ])
        self.assertFalse(SyntheticAidOffer.objects.exists())

    def test_raw_update_delete_and_duplicate_offer_rejected(self):
        row = self.offer()
        for fn in (
            lambda: SyntheticAidOffer.objects.filter(pk=row.pk).update(
                actor_user_id=self.officer.pk
            ),
            lambda: SyntheticAidOffer.objects.filter(pk=row.pk).delete(),
            lambda: SyntheticAidOffer.objects.bulk_create([
                SyntheticAidOffer(
                    application=self.app, student_selection=self.selected,
                    actor_user=self.officer, bucket="need", amount_cents=25000,
                )
            ]),
        ):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    fn()
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)

    def test_concurrent_officer_retries_share_one_offer(self):
        results = Queue()

        def worker():
            try:
                row = self.offer()
                results.put(("ok", str(row.pk)))
            except Exception as exc:
                results.put(("error", type(exc).__name__))
            finally:
                connections["default"].close()

        workers = [Thread(target=worker, daemon=True) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=12)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        outcomes = [results.get_nowait() for _ in workers]
        self.assertTrue(all(item[0] == "ok" for item in outcomes), outcomes)
        self.assertEqual(outcomes[0][1], outcomes[1][1])
        self.assertEqual(SyntheticAidOffer.objects.count(), 1)
