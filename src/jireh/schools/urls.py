"""Test-only routing of read-only family household endpoints."""

from django.urls import path

from . import views
from .redemption_views import test_household_redemption
from .session_views import test_family_login, test_family_logout
from jireh.financial_aid.views import staff_application_index, staff_application_detail
from jireh.financial_aid.family_views import family_annual_draft
from jireh.financial_aid.student_views import selected_students, select_student


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
]
