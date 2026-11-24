"""Test-only routing of read-only family household endpoints."""

from django.urls import path

from . import views
from .redemption_views import test_household_redemption
from .session_views import test_family_login, test_family_logout
from jireh.financial_aid.views import staff_application_index, staff_application_detail, staff_draft_workload
from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.synthetic_questionnaire_views import (
    read_synthetic_family_questionnaire_preview,
)
from jireh.financial_aid.student_views import selected_students, select_student
from jireh.financial_aid.synthetic_document_views import (
    list_fictional_documents, create_fictional_document, read_fictional_document,
    remove_fictional_document,
)
from jireh.financial_aid.synthetic_demo_views import (
    record_synthetic_family_receipt, read_synthetic_family_receipt,
    record_synthetic_staff_offer, read_synthetic_family_offer_list,
    read_synthetic_staff_offer,
    read_synthetic_staff_assessment,
)


urlpatterns = [
    path("test-auth/login/", test_family_login, name="jireh_test_family_login"),
    path("test-auth/logout/", test_family_logout, name="jireh_test_family_logout"),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "invitation/redeem/",
        test_household_redemption,
        name="jireh_test_household_redemption",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/",
        views.household_detail,
        name="jireh_household_detail",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/students/",
        views.household_students,
        name="jireh_household_students",
    ),

    path(
        "api/v1/schools/<uuid:school_id>/academic-years/"
        "<uuid:academic_year_id>/aid-applications/draft-workload/",
        staff_draft_workload,
        name="jireh_staff_application_summary",
    ),

    path(
        "api/v1/schools/<uuid:school_id>/academic-years/"
        "<uuid:academic_year_id>/aid-applications/",
        staff_application_index,
        name="jireh_staff_application_index",
    ),

    path(
        "api/v1/schools/<uuid:school_id>/academic-years/"
        "<uuid:academic_year_id>/aid-applications/<uuid:application_id>/",
        staff_application_detail,
        name="jireh_staff_application_detail",
    ),

    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/",
        family_annual_draft,
        name="jireh_family_annual_draft",
    ),

    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/students/",
        selected_students,
        name="jireh_aid_selected_students",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/students/"
        "<uuid:student_id>/",
        select_student,
        name="jireh_aid_select_student",
    ),
    # Fixed fictional financial rows only; no answers accepted or persisted.
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/questionnaire/<slug:scenario_id>/",
        read_synthetic_family_questionnaire_preview,
        name="jireh_test_synthetic_family_questionnaire_preview",
    ),
    # Fixed server-owned PDF fixture only. No user-uploaded bytes, production
    # document routes or externally accessible storage are exposed here.
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/documents/",
        list_fictional_documents, name="jireh_test_fictional_document_list",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/documents/create/",
        create_fictional_document, name="jireh_test_fictional_document_create",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/documents/<uuid:document_id>/read/",
        read_fictional_document, name="jireh_test_fictional_document_read",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/documents/<uuid:document_id>/remove/",
        remove_fictional_document, name="jireh_test_fictional_document_remove",
    ),
    # Disposable synthetic workflow only; production runtime never imports this URLConf.
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/receipt/",
        record_synthetic_family_receipt, name="jireh_test_synthetic_receipt_create",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/receipt/read/",
        read_synthetic_family_receipt, name="jireh_test_synthetic_receipt_read",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/households/<uuid:household_id>/"
        "academic-years/<uuid:academic_year_id>/aid-application/draft/"
        "synthetic/offers/",
        read_synthetic_family_offer_list, name="jireh_test_synthetic_family_offers",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/academic-years/<uuid:academic_year_id>/"
        "aid-applications/<uuid:application_id>/synthetic/assessment/<slug:scenario_id>/",
        read_synthetic_staff_assessment, name="jireh_test_synthetic_staff_assessment",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/academic-years/<uuid:academic_year_id>/"
        "aid-applications/<uuid:application_id>/synthetic/offers/"
        "<uuid:student_id>/",
        record_synthetic_staff_offer, name="jireh_test_synthetic_officer_offer",
    ),
    path(
        "api/v1/schools/<uuid:school_id>/academic-years/<uuid:academic_year_id>/"
        "aid-applications/<uuid:application_id>/synthetic/offers/"
        "<uuid:student_id>/read/",
        read_synthetic_staff_offer, name="jireh_test_synthetic_officer_offer_read",
    ),
]
