"""Test-only routing of read-only family household endpoints."""

from django.urls import path

from . import views
from jireh.financial_aid.views import staff_application_index


urlpatterns = [
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
]
