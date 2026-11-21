"""PostgreSQL-only verification and explicit known integrity gaps.

These tests run only against the disposable PostgreSQL 16 service.
Expected failures are security deficiencies to fix, NOT passing controls.
Remove each expectedFailure marker only after database-level enforcement
is implemented and the corrected test passes on real PostgreSQL.
"""

from datetime import date
from queue import Queue
from threading import Thread
from unittest import expectedFailure

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TransactionTestCase

from jireh.schools.models import (
    AcademicYear, Household, HouseholdAccess, HouseholdStudent, School, Student,
)
from jireh.schools.services import link_student_to_household

from .models import AidApplication, AidApplicationStudent, AidAuditEvent
from .services import get_or_create_annual_draft, select_student_for_draft


class PostgreSQLIntegrityTests(TransactionTestCase):
    """Real transactions, PostgreSQL constraints, and negative boundary probes."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires disposable PostgreSQL (no SQLite fallback).")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="postgres-parent", password="test-only-password"
        )
        self.school = School.objects.create(code="pg-school-a", name="School A")
        self.other_school = School.objects.create(
            code="pg-school-b", name="School B"
        )
        self.year = AcademicYear.objects.create(
            school=self.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        self.next_year = AcademicYear.objects.create(
            school=self.school, name="2027-28",
            start_date=date(2027, 8, 1), end_date=date(2028, 6, 30),
        )
        self.other_year = AcademicYear.objects.create(
            school=self.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        self.household = Household.objects.create(
            school=self.school, name="School A Household"
        )
        self.other_household = Household.objects.create(
            school=self.other_school, name="School B Household"
        )
        self.same_school_household = Household.objects.create(
            school=self.school, name="Separate Parent Household"
        )
        self.child = Student.objects.create(
            school=self.school, first_name="One", last_name="Child"
        )
        self.other_child = Student.objects.create(
            school=self.other_school, first_name="Other", last_name="Child"
        )
        self.link = link_student_to_household(
            school_id=self.school.pk,
            household_id=self.household.pk, student_id=self.child.pk,
        )
        self.other_link = link_student_to_household(
            school_id=self.school.pk,
            household_id=self.same_school_household.pk, student_id=self.child.pk,
        )
        HouseholdAccess.objects.create(household=self.household, user=self.user)

    def _draft(self, *, year=None):
        return get_or_create_annual_draft(
            user=self.user, school_id=self.school.pk,
            household_id=self.household.pk,
            academic_year_id=(year or self.year).pk,
        )

    def test_actual_database_is_postgresql_16(self):
        self.assertEqual(connection.vendor, "postgresql")
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            version = int(cursor.fetchone()[0])
        self.assertGreaterEqual(version, 160000)
        self.assertLess(version, 170000)

    def test_unique_annual_household_draft_constraint_on_postgresql(self):
        first = self._draft()
        second = self._draft(year=self.next_year)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplication.objects.filter(pk=second.pk).update(
                    academic_year_id=self.year.pk
                )
        self.assertEqual(
            AidApplication.objects.get(pk=second.pk).academic_year_id,
            self.next_year.pk,
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_postgresql_nowait_lock_rejects_concurrent_draft_claim(self):
        draft = self._draft()
        outcomes = Queue()

        def contender():
            # Django uses an independent DB connection in this worker thread.
            from django.db import connections
            try:
                with transaction.atomic():
                    AidApplication.objects.select_for_update(nowait=True).get(
                        pk=draft.pk
                    )
                outcomes.put("NO_LOCK")
            except DatabaseError as exc:
                outcomes.put(getattr(exc.__cause__, "sqlstate", "UNKNOWN"))
            finally:
                connections["default"].close()

        with transaction.atomic():
            AidApplication.objects.select_for_update().get(pk=draft.pk)
            thread = Thread(target=contender, daemon=True)
            thread.start()
            thread.join(timeout=8)
            self.assertFalse(thread.is_alive(), "Concurrent lock proof timed out")
            self.assertEqual(
                outcomes.get_nowait(), "55P03", "Expected PostgreSQL lock_not_available"
            )

    @expectedFailure
    def test_known_gap_raw_cross_school_household_student_update(self):
        # REQUIRED FUTURE CONTRACT: database must reject this bulk update.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HouseholdStudent.objects.filter(pk=self.link.pk).update(
                    student_id=self.other_child.pk
                )

    @expectedFailure
    def test_known_gap_raw_application_academic_year_school_mismatch(self):
        # REQUIRED FUTURE CONTRACT: app year must be from its own school.
        draft = self._draft()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplication.objects.filter(pk=draft.pk).update(
                    academic_year_id=self.other_year.pk
                )

    @expectedFailure
    def test_known_gap_raw_selection_cross_household_relink(self):
        # REQUIRED FUTURE CONTRACT: selection link belongs to application house.
        self._draft()
        selection = select_student_for_draft(
            user=self.user, school_id=self.school.pk,
            household_id=self.household.pk, academic_year_id=self.year.pk,
            student_id=self.child.pk,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidApplicationStudent.objects.filter(pk=selection.pk).update(
                    household_student_id=self.other_link.pk
                )

    @expectedFailure
    def test_known_gap_raw_audit_event_school_mismatch(self):
        # REQUIRED FUTURE CONTRACT: event school must match its application.
        draft = self._draft()
        event = AidAuditEvent.objects.get(
            application=draft, action=AidAuditEvent.ACTION_DRAFT_CREATED
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidAuditEvent.objects.filter(pk=event.pk).update(
                    school_id=self.other_school.pk
                )
