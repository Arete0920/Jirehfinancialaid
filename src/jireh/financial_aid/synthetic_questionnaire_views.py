"""Read-only, family-authorized fictional questionnaire preview.

This HTTP adapter is imported by disposable school/demo URLConfs only.
It accepts no financial answers, makes no writes and never exposes fixture
amounts, contributors or a completed legal application.
"""

import json
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .questionnaire_validation import QuestionnaireValidationError
from .services import selected_student_ids_for_draft
from .synthetic_questionnaire_preview import (
    FictionalScenarioNotFound,
    preview_fictional_financial_structure,
    require_synthetic_questionnaire_preview,
)


_CATALOG_FILE = (
    Path(__file__).resolve().parents[3] / "docs"
    / "questionnaire_v1_field_catalog.json"
)


@never_cache
@require_safe
def read_synthetic_family_questionnaire_preview(
    request, school_id, household_id, academic_year_id, scenario_id,
):
    """Validate fixed fictional sections after exact household draft authority.

    The catalog is loaded only AFTER authorizing the request, to avoid
    exposing fixture/catalog availability to an unauthenticated caller.
    """
    if request.GET:
        return JsonResponse({"detail": "Query parameters are not accepted."}, status=400)
    try:
        require_synthetic_questionnaire_preview()
        draft, _selected = selected_student_ids_for_draft(
            user=request.user,
            school_id=school_id,
            household_id=household_id,
            academic_year_id=academic_year_id,
        )
        preview = preview_fictional_financial_structure(
            user=request.user,
            school_id=draft.school_id,
            household_id=draft.household_id,
            academic_year_id=draft.academic_year_id,
            scenario_id=scenario_id,
            catalog=json.loads(_CATALOG_FILE.read_text(encoding="utf-8")),
        )
    except PermissionDenied:
        return JsonResponse({"detail": "Forbidden."}, status=403)
    except (Http404, FictionalScenarioNotFound):
        return JsonResponse({"detail": "Not found."}, status=404)
    except (
        OSError, UnicodeDecodeError, json.JSONDecodeError,
        QuestionnaireValidationError,
    ):
        return JsonResponse({"detail": "Fictional preview unavailable."}, status=503)

    return JsonResponse({
        **preview,
        "school_id": str(draft.school_id),
        "household_id": str(draft.household_id),
        "academic_year_id": str(draft.academic_year_id),
        "application_id": str(draft.pk),
    })
