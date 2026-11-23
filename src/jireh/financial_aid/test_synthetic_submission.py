"""Disposable, school-bound synthetic receipt and replay acceptance.

This suite never submits a real application, collects answers, charges a
household, or enables a production route.
"""
from datetime import date
from threading import Thread
from queue import Queue

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.http import Http404
from django.test import TestCase, TransactionTestCase, override_settings

from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, School, Student,
)
from jireh.schools.services import link_student_to_household
from .models import AidApplication, AidApplicationStudent, SyntheticAidSubmission
from .services import get_or_create_annual_draft, select_student_for_draft
from .synthetic_submission import record_synthetic_demo_submission


class SyntheticReceiptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(username="fictional-receipt-parent")
        cls.coparent = User.objects.create_user(username="fictional-receipt-coparent")
        cls.foreign = User.objects.create_user(username="fictional-foreign-parent")
        cls.school = School.objects.create(code="receipt-a", name="Synthetic School A")
        cls.other_school = School.objects.create(code="receipt-b", name="Synthetic School B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.household = Household.objects.create(school=cls.school, name="Fictional A")
        cls.other_household = Household.objects.create(
            school=cls.other_school, name="Fictional B"
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Fictional", last_name="Child"
        )
        cls.sibling = Student.objects.create(
            school=cls.school, first_name="Fictional", last_name="Sibling"
        )
        for child in (cls.child, cls.sibling):
            link_student_to_household(
                school_id=cls.school.pk, household_id=cls.household.pk,
                student_id=child.pk,
            )
        for user in (cls.parent, cls.coparent):
            HouseholdAccess.objects.create(household=cls.household, user=user)
        HouseholdAccess.objects.create(household=cls.other_household, user=cls.foreign)

    def draft(self):
        return get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
        )

    def selected(self):
        draft = self.draft()
        select_student_for_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )
        return draft

    def submit(self, **overrides):
        kw = dict(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
            accuracy_attested=True,
        )
        kw.update(overrides)
        return record_synthetic_demo_submission(**kw)

    def test_one_immutable_receipt_with_actor_timestamp_and_version(self):
        draft = self.selected()
        first = self.submit()
        retry = self.submit(user=self.coparent)
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(first.actor_user_id, self.parent.pk)
        self.assertEqual(first.application_id, draft.pk)
        self.assertEqual(first.consent_version, "synthetic-demo-v1")
        self.assertTrue(first.accuracy_attested)
        self.assertIsNotNone(first.created_at)
        self.assertEqual(SyntheticAidSubmission.objects.count(), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT")
        self.assertFalse(hasattr(first, "amount_cents"))
        self.assertNotIn(self.household.name, repr(first))
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            first.delete()

    def test_requires_explicit_attestation_and_selected_child(self):
        self.draft()
        for attestation in (None, False, 1, "true", {}, []):
            with self.subTest(attestation=attestation):
                with self.assertRaises(ValidationError):
                    self.submit(accuracy_attested=attestation)
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertEqual(SyntheticAidSubmission.objects.count(), 0)

    def test_wrong_school_household_year_and_ungranted_user_denied(self):
        self.selected()
        for overrides in (
            {"user": self.foreign},
            {"school_id": self.other_school.pk},
            {"household_id": self.other_household.pk},
            {"academic_year_id": self.other_year.pk},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises((Http404, PermissionDenied)):
                    self.submit(**overrides)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_revocation_prevents_new_and_existing_receipt_readback(self):
        self.selected()
        HouseholdAccess.objects.filter(
            household=self.household, user=self.parent
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self.submit()
        with self.assertRaises(Http404):
            self.submit(user=self.foreign)
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_child_selection_frozen_after_receipt(self):
        self.selected()
        self.submit()
        with self.assertRaises(ValidationError):
            select_student_for_draft(
                user=self.parent, school_id=self.school.pk,
                household_id=self.household.pk, academic_year_id=self.year.pk,
                student_id=self.sibling.pk,
            )
        self.assertEqual(
            AidApplicationStudent.objects.filter(application__household=self.household).count(), 1
        )

    def test_synthetic_switch_is_not_a_production_permission(self):
        self.selected()
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False):
            with self.assertRaises(PermissionDenied):
                self.submit()
        self.assertFalse(SyntheticAidSubmission.objects.exists())

    def test_database_constraints_disallow_false_attestation_and_other_version(self):
        self.selected()
        original = self.submit()
        for change in (
            {"accuracy_attested": False},
            {"consent_version": "unknown"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        SyntheticAidSubmission.objects.filter(pk=original.pk).update(**change)
        self.assertEqual(SyntheticAidSubmission.objects.count(), 1)


class SyntheticPostgresIntegrityTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL 16 required")
        User = get_user_model()
        self.parent = User.objects.create_user(username="pg-receipt-parent")
        self.school = School.objects.create(code="pg-receipt-a", name="PG Fictional A")
        self.year = AcademicYear.objects.create(
            school=self.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        self.household = Household.objects.create(school=self.school, name="PG Fictional")
        HouseholdAccess.objects.create(household=self.household, user=self.parent)
        self.child = Student.objects.create(
            school=self.school, first_name="PG", last_name="Child"
        )
        self.other_child = Student.objects.create(
            school=self.school, first_name="PG", last_name="Other"
        )
        for child in (self.child, self.other_child):
            link_student_to_household(
                school_id=self.school.pk, household_id=self.household.pk,
                student_id=child.pk,
            )
        self.draft = get_or_create_annual_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
        )
        select_student_for_draft(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )

    def submit(self):
        return record_synthetic_demo_submission(
            user=self.parent, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
            accuracy_attested=True,
        )

    def test_postgres_rejects_raw_update_delete_and_new_selection(self):
        record = self.submit()
        for action in (
            lambda: SyntheticAidSubmission.objects.filter(pk=record.pk).update(
                actor_user_id=self.parent.pk
            ),
            lambda: SyntheticAidSubmission.objects.filter(pk=record.pk).delete(),
        ):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    action()
        self.assertEqual(SyntheticAidSubmission.objects.count(), 1)

    def test_postgres_raw_selection_insert_is_frozen(self):
        self.submit()
        from jireh.schools.models import HouseholdStudent
        link = HouseholdStudent.objects.get(
            household=self.household, student=self.other_child
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplicationStudent.objects.bulk_create([
                    AidApplicationStudent(application=self.draft, household_student=link)
                ])
        self.assertEqual(AidApplicationStudent.objects.filter(application=self.draft).count(), 1)

    def test_postgres_parallel_submissions_are_single_receipt(self):
        results = Queue()

        def worker():
            try:
                item = self.submit()
                results.put(("ok", str(item.pk)))
            except Exception as error:
                results.put(("error", type(error).__name__))
            finally:
                connections["default"].close()

        a = Thread(target=worker, daemon=True)
        b = Thread(target=worker, daemon=True)
        a.start()
        b.start()
        a.join(12)
        b.join(12)
        self.assertFalse(a.is_alive() or b.is_alive(), "Concurrent synthetic receipt timed out")
        recorded = [results.get_nowait() for _ in range(2)]
        self.assertTrue(all(kind == "ok" for kind, _ in recorded), recorded)
        self.assertEqual(recorded[0][1], recorded[1][1])
        self.assertEqual(SyntheticAidSubmission.objects.count(), 1)
