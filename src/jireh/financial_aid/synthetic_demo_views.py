"""Disposable HTTP adaptation for the fictional family/officer aid sequence.

Imported ONLY by jireh.schools.urls (test settings and loopback demo).
The independently deployed runtime URLConf is healthz-only and never imports
this module. No real applicant, questionnaire, award, payment or ledger routes.
"""
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .offer_contract import OfferContractError
from .synthetic_submission import (
    record_synthetic_demo_submission, read_synthetic_demo_submission,
)
from .synthetic_offers import (
    record_synthetic_officer_offer, read_synthetic_family_offers,
)


def _denied(error):
    if isinstance(error, PermissionDenied):
        return JsonResponse({"detail": "Forbidden."}, status=403)
    if isinstance(error, Http404):
        return JsonResponse({"detail": "Not found."}, status=404)
    return JsonResponse({"detail": "Synthetic action unavailable."}, status=409)


@never_cache
@csrf_protect
@require_POST
def record_synthetic_family_receipt(request, school_id, household_id, academic_year_id):
    """Fictional, explicitly attested receipt, never a legal submission."""
    if request.content_type != "application/json":
        return JsonResponse({"detail": "Expected JSON."}, status=400)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict) or set(payload) != {"accuracy_attested"}:
        return JsonResponse({"detail": "Unsupported synthetic request."}, status=400)
    try:
        receipt = record_synthetic_demo_submission(
            user=request.user, school_id=school_id,
            household_id=household_id, academic_year_id=academic_year_id,
            accuracy_attested=payload["accuracy_attested"],
        )
    except (PermissionDenied, Http404, ValidationError) as error:
        return _denied(error)
    return JsonResponse({
        "application_id": str(receipt.application_id),
        "receipt_id": str(receipt.pk),
        "consent_version": receipt.consent_version,
        "status": "SYNTHETIC_RECEIPT",
    })


@never_cache
@require_GET
def read_synthetic_family_receipt(request, school_id, household_id, academic_year_id):
    try:
        receipt = read_synthetic_demo_submission(
            user=request.user, school_id=school_id,
            household_id=household_id, academic_year_id=academic_year_id,
        )
    except (PermissionDenied, Http404) as error:
        return _denied(error)
    return JsonResponse({
        "application_id": str(receipt.application_id),
        "receipt_id": str(receipt.pk),
        "consent_version": receipt.consent_version,
        "status": "SYNTHETIC_RECEIPT",
    })


@never_cache
@csrf_protect
@require_POST
def record_synthetic_staff_offer(
    request, school_id, academic_year_id, application_id, student_id
):
    """Only a fictional $250 need offer; no input amount accepted."""
    if request.body:
        return JsonResponse({"detail": "No offer payload is permitted."}, status=400)
    try:
        offer = record_synthetic_officer_offer(
            user=request.user, school_id=school_id,
            academic_year_id=academic_year_id, application_id=application_id,
            student_id=student_id,
        )
    except (PermissionDenied, Http404, ValidationError, OfferContractError) as error:
        return _denied(error)
    return JsonResponse({
        "application_id": str(offer.application_id),
        "student_id": str(offer.student_selection.household_student.student_id),
        "bucket": offer.bucket,
        "amount_cents": offer.amount_cents,
        "status": "SYNTHETIC_OFFERED",
    })


@never_cache
@require_GET
def read_synthetic_family_offer_list(
    request, school_id, household_id, academic_year_id
):
    try:
        offers = read_synthetic_family_offers(
            user=request.user, school_id=school_id,
            household_id=household_id, academic_year_id=academic_year_id,
        )
    except (PermissionDenied, Http404) as error:
        return _denied(error)
    return JsonResponse({
        "synthetic": True,
        "offers": [
            {
                "application_id": row.application_id,
                "student_id": row.student_id,
                "bucket": row.bucket,
                "amount_cents": row.amount_cents,
                "status": row.status,
            }
            for row in offers
        ],
    })
