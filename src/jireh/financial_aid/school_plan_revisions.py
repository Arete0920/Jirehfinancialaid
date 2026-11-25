"""Scoped persistence for fictional school-year planning inputs."""

from dataclasses import asdict

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from jireh.schools.access import require_aid_director_access
from jireh.schools.models import AcademicYear

from .annual_school_plan import FictionalAnnualSchoolPlan
from .models import FictionalSchoolPlanRevision


def _authorized_year(user, school_id, academic_year_id, *, lock=False):
    if getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True:
        raise PermissionDenied("Fictional school planning is disabled.")
    school = require_aid_director_access(user, school_id=school_id)
    years = AcademicYear.objects.for_school(school.pk)
    if lock:
        years = years.select_for_update()
    return get_object_or_404(years, pk=academic_year_id)


def read_fictional_school_plan(*, user, school_id, academic_year_id, revision=None):
    """Read the current or an exact historical revision in the director's school."""
    year = _authorized_year(user, school_id, academic_year_id)
    plans = FictionalSchoolPlanRevision.objects.filter(school_id=year.school_id, academic_year=year)
    if revision is not None:
        if type(revision) is not int or revision < 1:
            raise ValidationError("Invalid school plan revision.")
        return plans.filter(revision=revision).first()
    return plans.order_by("-revision").first()


@transaction.atomic
def record_fictional_school_plan(*, user, school_id, academic_year_id, plan):
    """Append a validated revision, reusing an identical currently saved plan."""
    year = _authorized_year(user, school_id, academic_year_id, lock=True)
    if type(plan) is not FictionalAnnualSchoolPlan:
        raise ValidationError("Invalid fictional school plan.")
    current = (FictionalSchoolPlanRevision.objects.filter(school_id=year.school_id, academic_year=year)
               .order_by("-revision").first())
    if current is not None and current.as_plan() == plan:
        return current
    payload = asdict(plan)
    payload["grade_bands"] = list(payload["grade_bands"])
    return FictionalSchoolPlanRevision.objects.create(
        school_id=year.school_id, academic_year=year, created_by=user,
        revision=1 if current is None else current.revision + 1, plan_payload=payload,
    )
