"""Test-only routing of read-only family household endpoints."""

from django.urls import path

from . import views


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
]
