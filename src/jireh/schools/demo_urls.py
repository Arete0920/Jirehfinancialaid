"""Synthetic-only browser routes, never included by standalone runtime."""

from django.urls import path
from .demo_views import demo_page, demo_config
from .demo_director_summary import director_database_truth_demo
from .urls import urlpatterns as test_only_urls

urlpatterns = [
    path("local-demo/", demo_page, name="jireh_local_demo"),
    path("local-demo/director-summary/", director_database_truth_demo, name="jireh_demo_director_summary"),
    path("local-demo/config/", demo_config, name="jireh_local_demo_config"),
    *test_only_urls,
]
