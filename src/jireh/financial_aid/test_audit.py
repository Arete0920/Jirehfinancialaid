"""Transactionally recorded Jireh draft and child-selection audit facts.

No event contains financial amounts, household answers or document content.
The schema covers only successful DRAFT_CREATED and STUDENT_SELECTED events.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School, Student
from jireh.schools.services import link_student_to_household

from .models import AidApplication, AidApplicationStudent, AidAuditEvent
from .services import get_or_create_annual_draft, select_student_for_draft


class DraftAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.parent = User.objects.create_user(
            username="parent-one", password="test-password"
        )
        cls.co_parent = User.objects.create_user(
            username="co-parent", password="test-password"
        )
        cls.other_parent = User.objects.create_user(
            username="parent-two", password="test-password"
        )
        cls.school = School.objects.create(code="school-a", name="School A")
        cls.other_school = School.objects.create(code="school-b", name="School B")
        cls.year = AcademicYear.objects.create(
            school=cls.school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.other_year = AcademicYear.objects.create(
            school=cls.other_school, name="2026-27",
            start_date=date(2026, 8, 1), end_date=date(2027, 6, 30),
        )
        cls.household = Household.objects.create(
            school=cls.school, name="Primary Household"
        )
        cls.separate = Household.objects.create(
            school=cls.school, name="Separate Parent Household"
        )
        cls.unrelated = Household.objects.create(
            school=cls.other_school, name="Other School Household"
        )
        cls.child = Student.objects.create(
            school=cls.school, first_name="Sample", last_name="Child"
        )
        cls.sibling = Student.objects.create(
            school=cls.school, first_name="Other", last_name="Child"
        )
        cls.unlinked = Student.objects.create(
            school=cls.school, first_name="Unlinked", last_name="Child"
        )
        cls.other_student = Student.objects.create(
            school=cls.other_school, first_name="Different", last_name="Child"
        )
        for household, student in (
            (cls.household, cls.child),
            (cls.household, cls.sibling),
            (cls.separate, cls.child),
            (cls.unrelated, cls.other_student),
        ):
            link_student_to_household(
                school_id=household.school_id,
                household_id=household.pk,
                student_id=student.pk,
            )
        for user, household in (
            (cls.parent, cls.household),
            (cls.co_parent, cls.household),
            (cls.other_parent, cls.separate),
        ):
            HouseholdAccess.objects.create(
                household=household, user=user
            )

    def _draft(self, *, user=None, household=None, school=None, year=None):
        return get_or_create_annual_draft(
            user=self.parent if user is None else user,
            school_id=(school or self.school).pk,
            household_id=(household or self.household).pk,
            academic_year_id=(year or self.year).pk,
        )

    def _select(self, *, user=None, household=None, student=None):
        return select_student_for_draft(
            user=self.parent if user is None else user,
            school_id=self.school.pk,
            household_id=(household or self.household).pk,
            academic_year_id=self.year.pk,
            student_id=(student or self.child).pk,
        )

    def test_first_draft_records_actor_school_and_timestamp(self):
        draft = self._draft()
        events = list(AidAuditEvent.objects.all())
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.action, AidAuditEvent.ACTION_DRAFT_CREATED)
        self.assertEqual(event.school_id, self.school.pk)
        self.assertEqual(event.application_id, draft.pk)
        self.assertEqual(event.actor_user_id, self.parent.pk)
        self.assertIsNone(event.student_selection_id)
        self.assertIsNotNone(event.created_at)

    def test_repeated_draft_requests_record_only_first_creator(self):
        first = self._draft()
        again = self._draft(user=self.co_parent)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(AidAuditEvent.objects.count(), 1)
        self.assertEqual(AidAuditEvent.objects.get().actor_user_id, self.parent.pk)

    def test_selection_records_actor_and_correct_student_selection(self):
        draft = self._draft()
        selection = self._select()
        selected = AidAuditEvent.objects.get(
            action=AidAuditEvent.ACTION_STUDENT_SELECTED
        )
        self.assertEqual(selected.school_id, self.school.pk)
        self.assertEqual(selected.application_id, draft.pk)
        self.assertEqual(selected.student_selection_id, selection.pk)
        self.assertEqual(selected.actor_user_id, self.parent.pk)
        self.assertEqual(AidAuditEvent.objects.count(), 2)

    def test_repeated_selection_does_not_duplicate_audit_record(self):
        self._draft()
        first = self._select()
        again = self._select()
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(
            AidAuditEvent.objects.filter(
                action=AidAuditEvent.ACTION_STUDENT_SELECTED
            ).count(), 1
        )

    def test_multiple_children_create_one_draft_and_two_selection_events(self):
        self._draft()
        self._select()
        self._select(student=self.sibling)
        self.assertEqual(AidApplication.objects.count(), 1)
        self.assertEqual(AidApplicationStudent.objects.count(), 2)
        self.assertEqual(AidAuditEvent.objects.count(), 3)

    def test_separate_households_have_independent_audit_events(self):
        original = self._draft()
        other = self._draft(user=self.other_parent, household=self.separate)
        self._select()
        self._select(user=self.other_parent, household=self.separate)
        self.assertNotEqual(original.pk, other.pk)
        self.assertEqual(AidAuditEvent.objects.count(), 4)
        self.assertEqual(
            AidAuditEvent.objects.filter(application=original).count(), 2
        )
        self.assertEqual(
            AidAuditEvent.objects.filter(application=other).count(), 2
        )

    def test_unauthorized_and_unlinked_operations_add_no_audit_events(self):
        self._draft()
        with self.assertRaises(Http404):
            self._select(user=self.other_parent)
        with self.assertRaises(Http404):
            self._select(student=self.unlinked)
        with self.assertRaises(Http404):
            self._draft(school=self.other_school, year=self.other_year)
        self.assertEqual(AidAuditEvent.objects.count(), 1)

    def test_revoked_access_cannot_append_audit_event(self):
        self._draft()
        HouseholdAccess.objects.filter(
            household=self.household, user=self.parent
        ).update(is_active=False)
        with self.assertRaises(Http404):
            self._select()
        self.assertEqual(AidAuditEvent.objects.count(), 1)

    def test_audit_model_rejects_wrong_school_or_application(self):
        draft = self._draft()
        with self.assertRaises(ValidationError):
            AidAuditEvent.objects.create(
                school=self.other_school,
                application=draft,
                actor_user=self.parent,
                action=AidAuditEvent.ACTION_DRAFT_CREATED,
            )
        self.assertEqual(AidAuditEvent.objects.count(), 1)

    def test_student_event_requires_matching_application_and_selection(self):
        original = self._draft()
        selection = self._select()
        other = self._draft(user=self.other_parent, household=self.separate)
        with self.assertRaises(ValidationError):
            AidAuditEvent.objects.create(
                school=self.school,
                application=other,
                actor_user=self.other_parent,
                action=AidAuditEvent.ACTION_STUDENT_SELECTED,
                student_selection=selection,
            )
        with self.assertRaises(ValidationError):
            AidAuditEvent.objects.create(
                school=self.school,
                application=original,
                actor_user=self.parent,
                action=AidAuditEvent.ACTION_STUDENT_SELECTED,
            )
        self.assertEqual(AidAuditEvent.objects.count(), 3)

    def test_database_rejects_invalid_action_or_duplicate_draft_creation(self):
        first = self._draft()
        second = self._draft(user=self.other_parent, household=self.separate)
        event1 = AidAuditEvent.objects.get(
            application=first, action=AidAuditEvent.ACTION_DRAFT_CREATED
        )
        event2 = AidAuditEvent.objects.get(
            application=second, action=AidAuditEvent.ACTION_DRAFT_CREATED
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidAuditEvent.objects.filter(pk=event2.pk).update(
                    application_id=first.pk
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidAuditEvent.objects.filter(pk=event1.pk).update(
                    action=AidAuditEvent.ACTION_STUDENT_SELECTED
                )

    def test_database_prevents_duplicate_student_selection_event(self):
        self._draft()
        selection1 = self._select()
        selection2 = self._select(student=self.sibling)
        event2 = AidAuditEvent.objects.get(
            student_selection_id=selection2.pk
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AidAuditEvent.objects.filter(pk=event2.pk).update(
                    student_selection_id=selection1.pk
                )

    def test_event_instances_refuse_direct_edits_and_deletes(self):
        self._draft()
        event = AidAuditEvent.objects.get()
        event.action = "OTHER"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_application_cannot_be_ordinary_deleted_when_audited(self):
        draft = self._draft()
        with self.assertRaises(ProtectedError):
            draft.delete()

    def test_draft_transaction_rolls_back_if_audit_cannot_be_saved(self):
        with patch.object(
            AidAuditEvent, "save", side_effect=RuntimeError("audit unavailable")
        ):
            with self.assertRaises(RuntimeError):
                self._draft()
        self.assertFalse(AidApplication.objects.exists())
        self.assertFalse(AidAuditEvent.objects.exists())

    def test_selection_transaction_rolls_back_if_audit_cannot_be_saved(self):
        self._draft()
        with patch.object(
            AidAuditEvent, "save", side_effect=RuntimeError("audit unavailable")
        ):
            with self.assertRaises(RuntimeError):
                self._select()
        self.assertFalse(AidApplicationStudent.objects.exists())
        self.assertEqual(AidAuditEvent.objects.count(), 1)

    def test_scoped_audit_query_requires_school_id(self):
        self._draft()
        with self.assertRaises(ValueError):
            AidAuditEvent.objects.for_school(None)
        self.assertEqual(
            AidAuditEvent.objects.for_school(self.school.pk).count(), 1
        )
        self.assertEqual(
            AidAuditEvent.objects.for_school(self.other_school.pk).count(), 0
        )

    def test_existing_test_only_http_paths_emit_audit_events(self):
        self.client.force_login(self.parent)
        url = reverse(
            "jireh_family_annual_draft",
            kwargs={
                "school_id": self.school.pk,
                "household_id": self.household.pk,
                "academic_year_id": self.year.pk,
            },
        )
        self.assertEqual(self.client.post(url).status_code, 200)
        select_url = reverse(
            "jireh_aid_select_student",
            kwargs={
                "school_id": self.school.pk,
                "household_id": self.household.pk,
                "academic_year_id": self.year.pk,
                "student_id": self.child.pk,
            },
        )
        self.assertEqual(self.client.post(select_url).status_code, 200)
        self.assertEqual(
            set(AidAuditEvent.objects.values_list("action", flat=True)),
            {
                AidAuditEvent.ACTION_DRAFT_CREATED,
                AidAuditEvent.ACTION_STUDENT_SELECTED,
            },
        )
