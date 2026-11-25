from dataclasses import replace
from datetime import timedelta
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import TestCase, override_settings

from jireh.schools.demo_seed import seed_synthetic_browser_demo
from jireh.schools.models import AcademicYear, SchoolStaffAccess

from .annual_school_plan import FICTIONAL_15145_PLAN
from .models import FictionalSchoolPlanRevision
from .school_plan_revisions import read_fictional_school_plan, record_fictional_school_plan


class FictionalSchoolPlanRevisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_synthetic_browser_demo()

    def scope(self):
        return {"user": self.demo["director_a"], "school_id": self.demo["school_a"].pk,
                "academic_year_id": self.demo["year_a"].pk}

    def test_versions_and_identical_retries_preserve_historical_results(self):
        scope = self.scope()
        self.assertIsNone(read_fictional_school_plan(**scope))
        first = record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **scope)
        self.assertEqual(record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **scope).pk, first.pk)
        updated = replace(FICTIONAL_15145_PLAN, annual_aid_budget_cents=28_000_000)
        second = record_fictional_school_plan(plan=updated, **scope)
        self.assertEqual((first.revision, second.revision), (1, 2))
        self.assertEqual(second.created_by_id, scope["user"].pk)
        self.assertEqual(read_fictional_school_plan(**scope).as_plan(), updated)
        self.assertEqual(read_fictional_school_plan(**scope, revision=1).as_plan(), FICTIONAL_15145_PLAN)
        self.assertIsNone(read_fictional_school_plan(**scope, revision=3))
        original_year = self.demo["year_a"]
        later_year = AcademicYear.objects.create(school=original_year.school, name="Later fictional year",
            start_date=original_year.start_date + timedelta(days=366),
            end_date=original_year.end_date + timedelta(days=366))
        later_scope = scope | {"academic_year_id": later_year.pk}
        self.assertIsNone(read_fictional_school_plan(**later_scope))
        self.assertEqual(record_fictional_school_plan(plan=updated, **later_scope).revision, 1)

    def test_wrong_school_year_revocation_and_disabled_runtime_fail_closed(self):
        scope = self.scope()
        record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **scope)
        with self.assertRaises(Http404):
            read_fictional_school_plan(**(scope | {"user": self.demo["director_b"]}))
        with self.assertRaises(Http404):
            record_fictional_school_plan(plan=FICTIONAL_15145_PLAN,
                **(scope | {"academic_year_id": self.demo["year_b"].pk}))
        with override_settings(JIREH_SYNTHETIC_SUBMISSION_ONLY=False), self.assertRaises(PermissionDenied):
            read_fictional_school_plan(**scope)
        grant = SchoolStaffAccess.objects.get(school_id=scope["school_id"], user=scope["user"])
        grant.is_active = False
        grant.save(update_fields=["is_active"])
        with self.assertRaises(Http404):
            record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **scope)
        self.assertEqual(FictionalSchoolPlanRevision.objects.count(), 1)

    def test_instance_mutations_and_invalid_payload_are_rejected(self):
        revision = record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **self.scope())
        revision.plan_payload = {}
        with self.assertRaises(ValidationError):
            revision.save()
        with self.assertRaises(ValidationError):
            revision.delete()
        with self.assertRaisesMessage(ValidationError, "Invalid fictional school plan"):
            FictionalSchoolPlanRevision.objects.create(school_id=revision.school_id,
                academic_year_id=revision.academic_year_id,
                created_by_id=revision.created_by_id, revision=2, plan_payload={"grade_bands": []})

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL trigger evidence")
    def test_postgresql_rejects_direct_revision_changes_and_deletion(self):
        revision = record_fictional_school_plan(plan=FICTIONAL_15145_PLAN, **self.scope())
        with self.assertRaises(IntegrityError), transaction.atomic():
            FictionalSchoolPlanRevision.objects.filter(pk=revision.pk).update(revision=2)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM financial_aid_fictionalschoolplanrevision WHERE id = %s", [revision.pk])
        for change in ({"academic_year": self.demo["year_b"]}, {"created_by": self.demo["director_b"]}):
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():
                values = {"school_id": revision.school_id, "academic_year": revision.academic_year,
                          "created_by": revision.created_by, "revision": 2, "plan_payload": revision.plan_payload}
                FictionalSchoolPlanRevision.objects.bulk_create([FictionalSchoolPlanRevision(**(values | change))])
        self.assertEqual(FictionalSchoolPlanRevision.objects.get(pk=revision.pk).revision, 1)
