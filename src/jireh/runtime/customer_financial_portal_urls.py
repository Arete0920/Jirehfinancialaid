"""Fixture-bound financial acceptance, reusing the existing workspace handlers."""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import path

from jireh.schools.workspace_contributor_exception import workspace_contributor_exception
from jireh.schools.workspace_documents import (
    workspace_documents, workspace_document_sample, workspace_document_upload,
    workspace_document_read, workspace_document_remove,
)
from jireh.schools.workspace_questionnaire import workspace_questionnaire
from jireh.schools.workspace_review import workspace_review
from .customer_financial_policy import financial_scope_allowed
from .customer_portal import _family_allowed, portal_only
from .customer_portal_urls import urlpatterns as portal_patterns


def fixture_family_only(view):
    @portal_only
    @wraps(view)
    def guarded(request, school_id, household_id, academic_year_id, *args, **kwargs):
        if not _family_allowed(request):
            raise PermissionDenied()
        if not financial_scope_allowed(school_id, household_id, academic_year_id):
            raise Http404()
        return view(request, school_id, household_id, academic_year_id, *args, **kwargs)
    return guarded


_FAMILY = "customer/family/<uuid:school_id>/<uuid:household_id>/<uuid:academic_year_id>/"
urlpatterns = [*portal_patterns,
    path(_FAMILY + "questionnaire/", fixture_family_only(workspace_questionnaire),
         name="jireh_workspace_questionnaire"),
    path(_FAMILY + "documents/", fixture_family_only(workspace_documents), name="jireh_workspace_documents"),
    path(_FAMILY + "documents/sample/<slug:variant>/", fixture_family_only(workspace_document_sample),
         name="jireh_workspace_document_sample"),
    path(_FAMILY + "documents/upload/", fixture_family_only(workspace_document_upload),
         name="jireh_workspace_document_upload"),
    path(_FAMILY + "documents/<uuid:document_id>/read/", fixture_family_only(workspace_document_read),
         name="jireh_workspace_document_read"),
    path(_FAMILY + "documents/<uuid:document_id>/remove/", fixture_family_only(workspace_document_remove),
         name="jireh_workspace_document_remove"),
    path(_FAMILY + "review/", fixture_family_only(workspace_review), name="jireh_workspace_review"),
    path(_FAMILY + "review/contributor-exception/", fixture_family_only(workspace_contributor_exception),
         name="jireh_workspace_contributor_exception"),
]
