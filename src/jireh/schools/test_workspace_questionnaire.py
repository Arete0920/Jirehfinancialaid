"""Acceptance for household-scoped fictional questionnaire contributors."""
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid5

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from jireh.financial_aid.models import SyntheticQuestionnaireDraft, SyntheticQuestionnaireEvent
from jireh.financial_aid.services import get_or_create_annual_draft
from jireh.financial_aid.synthetic_questionnaire_storage import (
    FictionalQuestionnairePolicy, read_fictional_questionnaire, save_fictional_questionnaire,
)
from .demo_seed import seed_synthetic_browser_demo
from .grant_admin import revoke_household_access
from .models import Household, HouseholdAccess, Student
from .services import link_student_to_household


_KEY = secrets.token_bytes(32)


@override_settings(
    ROOT_URLCONF="jireh.schools.customer_workspace_urls",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=True,
    JIREH_SYNTHETIC_QUESTIONNAIRE_KEY=_KEY,
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}],
)
class WorkspaceQuestionnaireContributorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture = seed_synthetic_browser_demo()
        cls.parent = fixture["parent"]
        cls.director = fixture["director_a"]
        cls.other_parent = get_user_model().objects.create_user(username="fictional-questionnaire-other-parent")
        other = Household.objects.create(school=fixture["school_a"], name="Separate fictional household")
        HouseholdAccess.objects.create(household=other, user=cls.other_parent)
        cls.ids = dict(school_id=fixture["school_a"].pk, household_id=fixture["household_a"].pk,
                       academic_year_id=fixture["year_a"].pk)
        cls.other_ids = dict(cls.ids, household_id=other.pk)
        cls.child = Student.objects.get(school_id=cls.ids["school_id"], first_name="Jordan")
        link_student_to_household(school_id=cls.other_ids["school_id"], household_id=other.pk,
                                  student_id=cls.child.pk)
        cls.draft = get_or_create_annual_draft(user=cls.parent, **cls.ids)
        get_or_create_annual_draft(user=cls.other_parent, **cls.other_ids)

    def setUp(self):
        self.url = reverse("jireh_workspace_questionnaire", kwargs=self.ids)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.parent)

    def _form(self, page, section="income", index=0):
        group = next(group for group in page.context["questionnaire_groups"]
                     if group["section"] == section)
        return group["formset"].forms[index]

    def _choices(self, page, section="income"):
        fields = self._form(page, section).fields
        self.assertIn("member", fields)
        return [value for value, _ in fields["member"].choices]

    def _post(self, member, revision=0, previous_rows=0, *, csrf=True, balances=False):
        payload = {"revision": revision}
        for section in ("income", "assets", "liabilities", "expenses"):
            payload[f"{section}-TOTAL_FORMS"] = int(section == "income")
            payload[f"{section}-INITIAL_FORMS"] = previous_rows if section == "income" else 0
        payload.update({
            "income-0-category": "EMPLOYMENT", "income-0-value": "765.43",
            "income-0-period_start": "2026-01-01", "income-0-period_end": "2026-12-31",
            "income-0-member": member,
        })
        if balances:
            for section, category in (("assets", "CASH"), ("liabilities", "MORTGAGE")):
                payload.update({
                    f"{section}-TOTAL_FORMS": 1,
                    f"{section}-0-category": category,
                    f"{section}-0-value": "50.00",
                    f"{section}-0-as_of_date": "2026-06-30",
                    f"{section}-0-member": member,
                })
        headers = {"HTTP_ORIGIN": "https://testserver"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = self.client.cookies["csrftoken"].value
        return self.client.post(self.url, urlencode(payload),
                                content_type="application/x-www-form-urlencoded", secure=True, **headers)

    def _read(self):
        return read_fictional_questionnaire(user=self.parent, **self.ids, key=_KEY)

    def test_existing_contributor_reads_back_and_can_be_corrected(self):
        legacy = str(uuid5(self.draft.pk, "fictional-contributor-v1"))
        catalog = json.loads((Path(__file__).resolve().parents[3] / "docs/questionnaire_v1_field_catalog.json")
                             .read_text(encoding="utf-8"))
        save_fictional_questionnaire(
            user=self.parent, **self.ids, key=_KEY, expected_revision=0, catalog=catalog,
            policy=FictionalQuestionnairePolicy(
                reporting_year=2026, min_cents=0, max_cents=100_000_000,
                categories=(("EMPLOYMENT",), ("CASH",), ("MORTGAGE",), ("HOUSING",)),
                member_ids=(legacy,),
            ),
            answers={"income": [{"category": "EMPLOYMENT", "amount": 12345,
                                 "period_start": "2026-01-01", "period_end": "2026-12-31",
                                 "contributor_id": legacy}]},
        )
        page = self.client.get(self.url, secure=True)
        self.assertContains(page, "Saved revision: 1")
        primary, secondary = self._choices(page)
        self.assertEqual(primary, legacy)
        self.assertEqual(self._form(page)["member"].value(), primary)
        self.assertEqual(self._choices(page, "assets"), [primary, secondary])
        self.assertEqual(self._choices(page, "liabilities"), [primary, secondary])
        self.assertNotIn("member", self._form(page, "expenses").fields)
        self.assertEqual(self._post(secondary, revision=1, previous_rows=1, balances=True).status_code, 302)
        page = self.client.get(self.url, secure=True)
        for section in ("income", "assets", "liabilities"):
            self.assertEqual(self._form(page, section)["member"].value(), secondary)
        revision, saved = self._read()
        self.assertEqual((revision, saved["income"][0]["contributor_id"]), (2, secondary))
        self.assertEqual(saved["assets"][0]["owner_member_id"], secondary)
        self.assertEqual(saved["liabilities"][0]["responsible_member_id"], secondary)
        self.assertEqual(self._post(primary, revision=1, previous_rows=1).status_code, 409)
        self.assertEqual(self._read(), (revision, saved))
        self.assertNotIn(secondary.encode(), bytes(SyntheticQuestionnaireDraft.objects.get().ciphertext))
        self.assertEqual(list(SyntheticQuestionnaireEvent.objects.order_by("revision")
                              .values_list("revision", flat=True)), [1, 2])

    def test_shared_student_confers_no_page_or_contributor_access(self):
        page = self.client.get(self.url, secure=True)
        own = self._choices(page)
        other_url = reverse("jireh_workspace_questionnaire", kwargs=self.other_ids)
        self.assertEqual(self.client.get(other_url, secure=True).status_code, 404)
        other_client = Client()
        other_client.force_login(self.other_parent)
        other_choices = self._choices(other_client.get(other_url, secure=True))
        self.assertFalse(set(own) & set(other_choices))
        for member in (other_choices[0], str(self.child.pk), "", "forged"):
            with self.subTest(member=member):
                self.assertContains(self._post(member), "Correct the highlighted fictional rows.", status_code=400)
        self.assertEqual(self._read(), (0, {}))
        self.assertFalse(SyntheticQuestionnaireEvent.objects.exists())

    def test_csrf_and_revoked_grant_deny_contributor_writes(self):
        secondary = self._choices(self.client.get(self.url, secure=True))[1]
        self.assertEqual(self._post(secondary, csrf=False).status_code, 403)
        revoke_household_access(actor=self.director, school_id=self.ids["school_id"],
                                household_id=self.ids["household_id"], subject_user_id=self.parent.pk)
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        self.assertEqual(self._post(secondary).status_code, 404)
        self.assertFalse(SyntheticQuestionnaireDraft.objects.exists())
