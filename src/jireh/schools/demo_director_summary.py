"""Read-only, database-truth director summary for the disposable Jireh demo.

Not a production reporting endpoint, submitted-application report, real award,
disbursement or payment view. Nothing here adds a financial questionnaire
write path or exposes this URL in jireh.runtime.urls.
"""

import secrets

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from jireh.financial_aid.models import (
    AidApplication,
    AidApplicationStudent,
    SYNTHETIC_DISCLOSURE_VERSION,
    SYNTHETIC_OFFER_AMOUNT_CENTS,
    SYNTHETIC_OFFER_BUCKET,
    SyntheticAidOffer,
    SyntheticAidSubmission,
)
from jireh.financial_aid.workload import (
    WorkloadIntegrityError,
    summarize_draft_workload,
)
from jireh.schools.access import require_aid_director_access
from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE
from jireh.schools.models import AcademicYear, School, SchoolStaffAccess


def _require_demo_director(user):
    if (
        settings.ROOT_URLCONF != "jireh.schools.demo_urls"
        or getattr(settings, "JIREH_SYNTHETIC_SUBMISSION_ONLY", False) is not True
    ):
        raise PermissionDenied("Demo summary disabled.")
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        raise PermissionDenied("Authentication required.")

    # Exactly one active school grant, not a preferred school supplied by the
    # browser, arbitrary query parameter or a shared student's membership.
    schools = list(
        School.objects.filter(
            code__in=(DEMO_SCHOOL_A_CODE, DEMO_SCHOOL_B_CODE),
            is_active=True,
            staff_access_grants__user_id=user.pk,
            staff_access_grants__is_active=True,
            staff_access_grants__role=SchoolStaffAccess.ROLE_AID_DIRECTOR,
        ).values_list("pk", flat=True).distinct()[:2]
    )
    if len(schools) != 1:
        raise Http404("Director school unavailable.")
    school = require_aid_director_access(user, school_id=schools[0])
    year = AcademicYear.objects.for_school(school.pk).filter(name="2026-27").first()
    if year is None:
        raise Http404("Director year unavailable.")
    return school, year


def _summary(school, year):
    applications = list(
        AidApplication.objects.for_school(school.pk)
        .filter(academic_year_id=year.pk)
        .values("id", "school_id", "academic_year_id", "household_id", "status")
    )
    selections = list(
        AidApplicationStudent.objects.for_school(school.pk)
        .filter(application__academic_year_id=year.pk)
        .values(
            "id", "application_id", "application__school_id",
            "application__academic_year_id", "application__household_id",
            "household_student__household_id", "household_student__student_id",
        )
    )
    facts = summarize_draft_workload(
        school_id=school.pk,
        academic_year_id=year.pk,
        applications=applications,
        selections=selections,
    )
    application_ids = {row["id"] for row in applications}
    selections_by_id = {row["id"]: row for row in selections}
    if len(selections_by_id) != len(selections):
        raise WorkloadIntegrityError("director_summary_unavailable")

    receipts = list(
        SyntheticAidSubmission.objects.filter(
            application__school_id=school.pk,
            application__academic_year_id=year.pk,
        ).values("application_id", "accuracy_attested", "consent_version")
    )
    receipt_ids = set()
    for receipt in receipts:
        app_id = receipt["application_id"]
        if (
            app_id not in application_ids
            or app_id in receipt_ids
            or receipt["accuracy_attested"] is not True
            or receipt["consent_version"] != SYNTHETIC_DISCLOSURE_VERSION
        ):
            raise WorkloadIntegrityError("director_summary_unavailable")
        receipt_ids.add(app_id)

    offers = list(
        SyntheticAidOffer.objects.filter(
            application__school_id=school.pk,
            application__academic_year_id=year.pk,
        ).values(
            "application_id", "student_selection_id",
            "student_selection__application_id",
            "student_selection__household_student__household_id",
            "bucket", "amount_cents",
        )
    )
    offer_selection_ids = set()
    for offer in offers:
        selection_id = offer["student_selection_id"]
        selected = selections_by_id.get(selection_id)
        if (
            selection_id in offer_selection_ids
            or selected is None
            or offer["application_id"] not in receipt_ids
            or offer["student_selection__application_id"] != offer["application_id"]
            or selected["application_id"] != offer["application_id"]
            or (
                offer["student_selection__household_student__household_id"]
                != selected["application__household_id"]
            )
            or offer["bucket"] != SYNTHETIC_OFFER_BUCKET
            or type(offer["amount_cents"]) is not int
            or offer["amount_cents"] != SYNTHETIC_OFFER_AMOUNT_CENTS
        ):
            raise WorkloadIntegrityError("director_summary_unavailable")
        offer_selection_ids.add(selection_id)

    return {
        "draft_households": facts["distinct_draft_households"],
        "draft_applications": facts["draft_application_records"],
        "selected_household_child_links": facts["selected_household_student_links"],
        "fictional_receipts": len(receipt_ids),
        "fictional_offers": len(offer_selection_ids),
        "fictional_offer_face_value_cents": len(offer_selection_ids) * SYNTHETIC_OFFER_AMOUNT_CENTS,
        "real_submitted_applications_reported": False,
        "real_awards_or_disbursements_reported": False,
        "data_source": "school_scoped_disposable_database",
        "synthetic_only": True,
    }


@never_cache
@require_GET
def director_database_truth_demo(request):
    """Human-readable director page: scoped saved facts, no fake sample KPIs."""
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    try:
        school, year = _require_demo_director(request.user)
        facts = _summary(school, year)
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except Http404:
        return JsonResponse({"detail": "Not found."}, status=404)
    except WorkloadIntegrityError:
        return JsonResponse({"detail": "Director summary unavailable."}, status=503)

    nonce = secrets.token_urlsafe(16)
    response = render(request, "jireh/demo_director_summary.html", {
        "school_name": school.name,
        "year_name": year.name,
        "facts": facts,
        "fictional_offer_dollars": f'{facts["fictional_offer_face_value_cents"] / 100:,.2f}',
        "csp_nonce": nonce,
    })
    response["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; "
        "form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response["X-Frame-Options"] = "DENY"
    response["X-Content-Type-Options"] = "nosniff"
    return response
