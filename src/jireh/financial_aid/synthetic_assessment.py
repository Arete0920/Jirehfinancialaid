"""Read-only assessment of fixed fictional inputs in disposable settings."""

import json
from pathlib import Path

from django.http import Http404
from django.shortcuts import get_object_or_404

from jireh.schools.access import require_aid_director_access
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE

from .assessment_contract import (
    BucketCalculationRule,
    CandidateAssessmentPolicy,
    calculate_candidate_assessment,
)
from .buckets import AidBucket
from .models import AidApplication
from .synthetic_questionnaire_preview import (
    require_synthetic_questionnaire_preview,
    validate_fictional_scenario,
)


_CATALOG_FILE = Path(__file__).resolve().parents[3] / "docs/questionnaire_v1_field_catalog.json"

# Invented ratios and caps to exercise rounding, capped amounts and zero buckets.
# Explicit inputs for this fixture do not establish school eligibility or policy.
_TEST_RULES = (
    BucketCalculationRule(AidBucket.NEED, 1, 1500, "HALF_UP", 10_000_000, 10_000),
    BucketCalculationRule(AidBucket.MISSION, 0, 1, "FLOOR", 0, 0),
    BucketCalculationRule(AidBucket.MARKETING, 0, 1, "FLOOR", 0, 0),
    BucketCalculationRule(AidBucket.MERIT, 1, 200, "CEILING", 2_000_000, 10_000),
    BucketCalculationRule(AidBucket.HARDSHIP, 1, 100, "FLOOR", 1_000_000, 5_000),
)


def preview_fictional_assessment(*, user, school_id, academic_year_id, application_id, scenario_id):
    require_synthetic_questionnaire_preview()
    school = require_aid_director_access(user, school_id=school_id)
    if school.code != DEMO_SCHOOL_A_CODE:
        raise Http404("Fictional assessment unavailable.")
    application = get_object_or_404(
        AidApplication.objects.for_school(school.pk),
        pk=application_id,
        academic_year_id=academic_year_id,
        academic_year__school_id=school.pk,
        household__school_id=school.pk,
        household__is_active=True,
        status=AidApplication.STATUS_DRAFT,
    )

    rows = validate_fictional_scenario(
        scenario_id=scenario_id,
        catalog=json.loads(_CATALOG_FILE.read_text(encoding="utf-8")),
    )
    scope = {"school_id": str(school.pk), "academic_year_id": str(application.academic_year_id)}
    return calculate_candidate_assessment(
        **scope,
        policy=CandidateAssessmentPolicy(
            **scope,
            policy_version="fictional-director-preview-v1",
            bucket_rules=_TEST_RULES,
            total_review_ceiling_cents=25_000,
        ),
        basis_cents_by_bucket={
            AidBucket.NEED: rows["income"].amount_cents,
            AidBucket.MISSION: 0,
            AidBucket.MARKETING: 0,
            AidBucket.MERIT: rows["assets"].balance_cents,
            AidBucket.HARDSHIP: rows["liabilities"].balance_cents,
        },
    )
