"""Independent acceptance router: no school/customer write or live routes."""
from django.urls import path

from .operator_portal import (
    operations_only, operator_begin, operator_complete, operator_home, operator_login, operator_logout,
)

urlpatterns = [
    path("operations/", operations_only(operator_home), name="jireh_operator_home"),
    path("operations/sign-in/", operations_only(operator_login), name="jireh_operator_login"),
    path("operations/begin/", operations_only(operator_begin), name="jireh_operator_begin"),
    path("operations/complete/", operations_only(operator_complete), name="jireh_operator_complete"),
    path("operations/sign-out/", operations_only(operator_logout), name="jireh_operator_logout"),
]
