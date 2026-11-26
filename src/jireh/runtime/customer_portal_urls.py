"""Explicit disposable portal URLConf; never imported by runtime.urls."""
from django.urls import path
from django.urls.resolvers import URLPattern

from .customer_portal import portal_case, portal_director, portal_family, portal_home, portal_logout, portal_only
from .customer_urls import urlpatterns as core_patterns

# Preserve the existing browser template's reverse names. Both names address
# the exact same guarded core endpoint, not duplicate business implementations.
_aliases = {"jireh_customer_draft": "jireh_workspace_draft", "jireh_customer_select": "jireh_workspace_select"}
urlpatterns = [*core_patterns, *[
    URLPattern(item.pattern, item.callback, item.default_args, name=_aliases[item.name])
    for item in core_patterns if item.name in _aliases
],
    path("customer/", portal_only(portal_home), name="jireh_workspace"),
    path("customer/sign-out/", portal_only(portal_logout), name="jireh_workspace_logout"),
    path("customer/family/<uuid:school_id>/<uuid:household_id>/<uuid:academic_year_id>/",
         portal_only(portal_family), name="jireh_workspace_family"),
    path("customer/director/<uuid:school_id>/<uuid:academic_year_id>/",
         portal_only(portal_director), name="jireh_workspace_director"),
    path("customer/director/<uuid:school_id>/<uuid:academic_year_id>/cases/<uuid:application_id>/",
         portal_only(portal_case), name="jireh_workspace_case"),
]
