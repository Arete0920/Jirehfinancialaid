"""Independent acceptance router: gated preparation only, no school/customer writes."""
from django.urls import path

from .operator_portal import (
    operations_only, operator_begin, operator_complete, operator_home, operator_login, operator_logout,
)
from .operator_preparation import operator_preparation

urlpatterns = [
    path("operations/", operations_only(operator_home), name="jireh_operator_home"),
    path("operations/preparation/", operations_only(operator_preparation), name="jireh_operator_preparation"),
    path("operations/sign-in/", operations_only(operator_login), name="jireh_operator_login"),
    path("operations/begin/", operations_only(operator_begin), name="jireh_operator_begin"),
    path("operations/complete/", operations_only(operator_complete), name="jireh_operator_complete"),
    path("operations/sign-out/", operations_only(operator_logout), name="jireh_operator_logout"),
]
