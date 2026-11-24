"""Four-section editable fictional questionnaire inside the customer workspace.

The server derives the fixture policy and the allowed contributors for each draft.
No live collection, attestation, submission, assessment or payment is enabled.
"""
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid5

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.forms import formset_factory
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from jireh.financial_aid.questionnaire_candidate import V1_ENUM_CHOICES
from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError
from jireh.financial_aid.services import selected_student_ids_for_draft
from .customer_workspace import _page

_SECTIONS = (
    ("income", "Income"),
    ("assets", "Assets"),
    ("liabilities", "Liabilities"),
    ("expenses", "Expenses"),
)
_FLOW = frozenset(("income", "expenses"))
_MEMBER_FIELD = {
    "income": "contributor_id",
    "assets": "owner_member_id",
    "liabilities": "responsible_member_id",
}
_MEMBER_LABEL = {
    "income": "Fictional income contributor",
    "assets": "Fictional asset owner",
    "liabilities": "Fictional person responsible for liability",
}
_FICTIONAL_CONTRIBUTORS = (
    # Keep the original fixture ID so existing encrypted rows retain their attribution.
    ("fictional-contributor-v1", "Fictional contributor 1"),
    ("fictional-contributor-2-v1", "Fictional contributor 2"),
)
_CATALOG = Path(__file__).resolve().parents[3] / "docs" / "questionnaire_v1_field_catalog.json"
_MAX_ROWS = 32
# These are explicitly fictional rehearsal parameters, not approved live policy.
_REPORTING_YEAR = 2026
_MAX_CENTS = 100_000_000


def _categories(section):
    return tuple(value for value in V1_ENUM_CHOICES[f"{section}.items[].category"]
                 if value != "OTHER_APPROVED")


def _date_field(label):
    return forms.DateField(
        label=label, input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )


class FictionalAmountForm(forms.Form):
    category = forms.ChoiceField()
    value = forms.DecimalField(
        label="Amount (USD)", max_digits=9, decimal_places=2,
        min_value=Decimal("0"), max_value=Decimal("1000000"),
    )

    def __init__(self, *args, section, contributors, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [
            ("", "Choose category"),
            *((value, value.replace("_", " ").title()) for value in _categories(section)),
        ]
        if section in _FLOW:
            self.fields["period_start"] = _date_field("Period start")
            self.fields["period_end"] = _date_field("Period end")
        else:
            self.fields["as_of_date"] = _date_field("Balance as of")
        if section in _MEMBER_FIELD:
            self.fields["member"] = forms.ChoiceField(
                label=_MEMBER_LABEL[section], choices=contributors,
                error_messages={"invalid_choice": "Choose a contributor listed for this draft."},
            )
            self.initial.setdefault("member", contributors[0][0])


class RevisionForm(forms.Form):
    revision = forms.IntegerField(
        min_value=0, max_value=2147483646, widget=forms.HiddenInput(),
    )


_AmountFormSet = formset_factory(
    FictionalAmountForm, extra=1, can_delete=True, max_num=_MAX_ROWS,
    validate_max=True, absolute_max=_MAX_ROWS,
)


def _initial(section, rows):
    result = []
    for row in rows:
        dates = ("period_start", "period_end") if section in _FLOW else ("as_of_date",)
        initial = {
            "category": row["category"],
            "value": Decimal(row["amount" if section in _FLOW else "balance"]) / 100,
            **{name: row[name] for name in dates},
        }
        if section in _MEMBER_FIELD:
            initial["member"] = row[_MEMBER_FIELD[section]]
        result.append(initial)
    return result


def _formsets(saved, contributors, data=None):
    return [
        {
            "section": section,
            "title": title,
            "count": len(saved.get(section, [])),
            "formset": _AmountFormSet(
                data=data, prefix=section, initial=_initial(section, saved.get(section, [])),
                form_kwargs={"section": section, "contributors": contributors},
            ),
        }
        for section, title in _SECTIONS
    ]


def _rows(groups):
    answers = {}
    for group in groups:
        section = group["section"]
        rows = []
        for form in group["formset"].forms:
            values = form.cleaned_data
            if not values or values.get("DELETE"):
                continue
            row = {"category": values["category"]}
            if section in _FLOW:
                row.update(
                    amount=int(values["value"] * 100),
                    period_start=values["period_start"].isoformat(),
                    period_end=values["period_end"].isoformat(),
                )
            else:
                row.update(
                    balance=int(values["value"] * 100),
                    as_of_date=values["as_of_date"].isoformat(),
                )
            if section in _MEMBER_FIELD:
                row[_MEMBER_FIELD[section]] = values["member"]
            rows.append(row)
        if rows:
            answers[section] = rows
    return answers


def _render(request, draft, groups, revision_form, revision, *, error="", status=200):
    response = _page(
        request, "questionnaire", household=draft.household, year=draft.academic_year,
        questionnaire_groups=groups, revision_form=revision_form, saved_revision=revision,
        questionnaire_error=error, max_questionnaire_rows=_MAX_ROWS,
        reporting_year=_REPORTING_YEAR,
    )
    response.status_code = status
    # Native same-origin form POSTs need an Origin/Referer accepted by CSRF.
    # Never send the questionnaire URL as a referrer to another origin.
    response["Referrer-Policy"] = "same-origin"
    return response


def _unavailable():
    return HttpResponse("Fictional questionnaire unavailable.", status=503)


@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST", "HEAD"])
def workspace_questionnaire(request, school_id, household_id, academic_year_id):
    if getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE", False) is not True:
        raise PermissionDenied("Fictional questionnaire disabled.")
    scope = dict(
        user=request.user, school_id=school_id, household_id=household_id,
        academic_year_id=academic_year_id,
    )
    draft, _ = selected_student_ids_for_draft(**scope)
    if request.GET:
        return HttpResponse("Query parameters are not accepted.", status=400)
    # This optional dependency must not break the existing basic local demo.
    try:
        from jireh.financial_aid.synthetic_questionnaire_storage import (
            FictionalQuestionnairePolicy, read_fictional_questionnaire,
            save_fictional_questionnaire,
        )
    except ImportError:
        return _unavailable()
    key = getattr(settings, "JIREH_SYNTHETIC_QUESTIONNAIRE_KEY", None)
    contributors = tuple((str(uuid5(draft.pk, fixture_id)), label)
                         for fixture_id, label in _FICTIONAL_CONTRIBUTORS)
    policy = FictionalQuestionnairePolicy(
        reporting_year=_REPORTING_YEAR, min_cents=0, max_cents=_MAX_CENTS,
        categories=tuple(_categories(section) for section, _ in _SECTIONS),
        member_ids=tuple(member_id for member_id, _ in contributors),
    )
    try:
        revision, saved = read_fictional_questionnaire(**scope, key=key)
        catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))
        # Never silently substitute a different contributor on correction.
        if any(row.get(field) not in policy.member_ids
               for section, field in _MEMBER_FIELD.items()
               for row in saved.get(section, [])):
            return _unavailable()
    except (QuestionnaireValidationError, OSError, UnicodeError, json.JSONDecodeError):
        return _unavailable()
    if request.method != "POST":
        return _render(request, draft, _formsets(saved, contributors),
                       RevisionForm(initial={"revision": revision}), revision)
    if request.content_type != "application/x-www-form-urlencoded":
        return HttpResponse("Invalid fictional form.", status=400)
    revision_form = RevisionForm(request.POST)
    if not revision_form.is_valid():
        return HttpResponse("Invalid revision.", status=400)
    if revision_form.cleaned_data["revision"] != revision:
        return HttpResponse("Saved draft changed. Return to the questionnaire and reload.", status=409)
    groups = _formsets(saved, contributors, request.POST)
    valid = [group["formset"].is_valid() for group in groups]
    # Management fields are client-controlled. A truncated formset must never
    # silently remove existing financial rows; explicit DELETE is required.
    if not all(valid) or any(
        group["formset"].initial_form_count() != group["count"]
        or group["formset"].total_form_count() < group["count"]
        for group in groups
    ):
        return _render(request, draft, groups, revision_form, revision,
                       error="Correct the highlighted fictional rows.", status=400)
    try:
        save_fictional_questionnaire(
            **scope, key=key, expected_revision=revision,
            catalog=catalog, policy=policy, answers=_rows(groups),
        )
    except QuestionnaireValidationError as exc:
        if str(exc) == "questionnaire_revision_conflict":
            return HttpResponse("Saved draft changed. Return to the questionnaire and reload.", status=409)
        return _render(request, draft, groups, revision_form, revision,
                       error="Fictional rows do not satisfy the reviewed test policy.", status=400)
    # Never render uncommitted form input as success. GET reloads encrypted DB state.
    return redirect("jireh_workspace_questionnaire", school_id, household_id, academic_year_id)
