"""Explicit customer acceptance allowlist; never production routing."""
from django.urls import path

from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import select_student
from .customer_workspace import (
    acceptance_only, workspace_case, workspace_director, workspace_family, workspace_home,
)
from .workspace_questionnaire import workspace_questionnaire
from .workspace_documents import (
    workspace_documents, workspace_document_sample, workspace_document_upload,
    workspace_document_read, workspace_document_remove,
)
from .session_views import test_family_login, test_family_logout

FAMILY = "workspace/family/<uuid:school_id>/<uuid:household_id>/<uuid:academic_year_id>/"
DIRECTOR = "workspace/director/<uuid:school_id>/<uuid:academic_year_id>/"

urlpatterns = [
    path("workspace/", acceptance_only(workspace_home), name="jireh_workspace"),
    path("workspace/sign-in/", acceptance_only(test_family_login), name="jireh_workspace_login"),
    path("workspace/sign-out/", acceptance_only(test_family_logout), name="jireh_workspace_logout"),
    path(FAMILY, acceptance_only(workspace_family), name="jireh_workspace_family"),
    path(FAMILY + "draft/", acceptance_only(family_annual_draft), name="jireh_workspace_draft"),
    path(FAMILY + "students/<uuid:student_id>/", acceptance_only(select_student),
         name="jireh_workspace_select"),
    path(FAMILY + "questionnaire/", acceptance_only(workspace_questionnaire),
         name="jireh_workspace_questionnaire"),
    path(FAMILY + "documents/", acceptance_only(workspace_documents), name="jireh_workspace_documents"),
    path(FAMILY + "documents/sample/<slug:variant>/", acceptance_only(workspace_document_sample),
         name="jireh_workspace_document_sample"),
    path(FAMILY + "documents/upload/", acceptance_only(workspace_document_upload),
         name="jireh_workspace_document_upload"),
    path(FAMILY + "documents/<uuid:document_id>/read/", acceptance_only(workspace_document_read),
         name="jireh_workspace_document_read"),
    path(FAMILY + "documents/<uuid:document_id>/remove/", acceptance_only(workspace_document_remove),
         name="jireh_workspace_document_remove"),
    path(DIRECTOR, acceptance_only(workspace_director), name="jireh_workspace_director"),
    path(DIRECTOR + "cases/<uuid:application_id>/", acceptance_only(workspace_case),
         name="jireh_workspace_case"),
]
