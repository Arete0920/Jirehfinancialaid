"""Disposable authenticated preparation; no activation or provisioning route."""
from dataclasses import asdict
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.test import Client, TransactionTestCase, override_settings

from . import test_operator_portal as portal_fixtures
from .demo_preparation_jobs import advance_synthetic_preparation
from .demo_setup_intents import record_synthetic_setup_intent
from .models import School, SchoolPreparationEvent, SchoolSetupIntent, SyntheticSchoolProvisioningReceipt
from .operator_webauthn_registry import revoke_registered_operator_credential
from .school_setup_preflight import SchoolSetupCandidate
from .synthetic_provisioning import provision_synthetic_inactive_school
from .test_first_director_mfa import FirstDirectorProofFixture
from .test_onboarding_rehearsal import FictionalOnboardingRehearsal


@override_settings(**portal_fixtures.OperatorPortalTests._overridden_settings)
class OperatorPreparationPortalTests(FirstDirectorProofFixture, FictionalOnboardingRehearsal, TransactionTestCase):
    get = portal_fixtures.OperatorPortalTests.get
    post = portal_fixtures.OperatorPortalTests.post
    login = portal_fixtures.OperatorPortalTests.login
    begin_portal = portal_fixtures.OperatorPortalTests.begin_portal
    assertion_for = portal_fixtures.OperatorPortalTests.assertion_for
    verify = portal_fixtures.OperatorPortalTests.verify

    def setUp(self):
        super().setUp()
        self.candidate = SchoolSetupCandidate(
            "synthetic-preparation-academy", "Synthetic Preparation Academy",
            "America/New_York", str(uuid4()),
        )
        self.enterContext(self.settings(
            JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=False,
            JIREH_OPERATOR_PREPARATION_ACCEPTANCE=True,
            JIREH_OPERATOR_PREPARATION_FIXTURE=(self.operator.pk, self.candidate),
        ))
        self.client = Client(enforce_csrf_checks=True)

    def command(self, action, key=None, **kwargs):
        return self.post("preparation", {"command": action, "request_key": key}, **kwargs)

    def current(self):
        response = self.get("preparation")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_authenticated_fixture_preparation_and_replay(self):
        self.assertEqual(self.get("preparation").status_code, 403)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.command("RECORD").status_code, 403)
        options = self.begin_portal()
        self.assertEqual(self.post("complete", {"assertion": self.assertion_for(options)}).status_code, 200)
        self.assertEqual(self.current()["state"], "NOT_RECORDED")
        self.assertNotIn("idempotency_key", self.current()["candidate"])
        self.assertEqual(self.command("RECORD", csrf=False).status_code, 403)
        for _ in range(2):
            self.assertEqual(self.command("RECORD").json(), {"recorded": True})
        self.assertEqual(self.current()["state"], "RECEIVED")
        self.assertEqual(SchoolSetupIntent.objects.count(), 1)
        self.assertEqual(self.command("RUN", str(uuid4())).status_code, 400)
        queued, run = str(uuid4()), str(uuid4())
        self.assertEqual(self.command("QUEUE", queued).json(), {"event": "QUEUED", "attempt": 1})
        self.assertEqual(self.current()["state"], "QUEUED")
        self.assertEqual(self.command("RUN", run).json(), {"event": "PREPARED", "attempt": 1})
        self.assertEqual(self.command("RUN", run).json(), {"event": "PREPARED", "attempt": 1})
        self.assertEqual(self.command("QUEUE", queued).json(), {"event": "QUEUED", "attempt": 1})
        self.assertEqual(self.current()["state"], "PREPARED")
        self.assertEqual(SchoolPreparationEvent.objects.count(), 3)
        self.assertEqual(self.command("RUN", str(uuid4())).status_code, 400)
        self.assertEqual(self.command("RETRY", str(uuid4())).status_code, 400)
        self.assertFalse(School.objects.exists())
        self.assertFalse(SyntheticSchoolProvisioningReceipt.objects.exists())

    def test_conflict_cleared_retry_is_explicit(self):
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.command("RECORD").status_code, 200)
        self.assertEqual(self.command("QUEUE", str(uuid4())).status_code, 200)
        conflict = School.objects.create(code=self.candidate.code, name="Fictional conflict", is_active=False)
        self.assertEqual(self.command("RUN", str(uuid4())).json(), {"event": "FAILED", "attempt": 1})
        self.assertFalse(self.current()["retry_available"])
        self.assertEqual(self.command("RETRY", str(uuid4())).status_code, 400)
        conflict.delete()
        self.assertTrue(self.current()["retry_available"])
        self.assertEqual(self.command("RETRY", str(uuid4())).json(), {"event": "REQUEUED", "attempt": 2})
        self.assertEqual(self.command("RUN", str(uuid4())).json(), {"event": "PREPARED", "attempt": 2})
        self.assertEqual(self.current()["state"], "PREPARED")
        self.assertEqual(self.current()["attempt"], 2)
        self.assertFalse(School.objects.exists())
        self.assertFalse(SyntheticSchoolProvisioningReceipt.objects.exists())

    def test_scope_profile_revoke_and_unmodified_provisioning_guards(self):
        self.assertEqual(self.verify().status_code, 200)
        self.assertContains(self.get(), 'id="preparation-form"')
        with self.settings(JIREH_OPERATOR_PREPARATION_ACCEPTANCE=False):
            self.assertNotContains(self.get(), 'id="preparation-form"')
        csrf_token = self.get("login").json()["csrf_token"]
        for flag in ("JIREH_OPERATOR_PREPARATION_ACCEPTANCE", "JIREH_OPERATOR_PORTAL_ACCEPTANCE",
                     "JIREH_SYNTHETIC_SETUP_INTENT_ONLY", "JIREH_SYNTHETIC_PREPARATION_JOB_ONLY"):
            with self.settings(**{flag: False}):
                response = self.command("RECORD", csrf=False, HTTP_X_CSRFTOKEN=csrf_token)
                self.assertEqual(response.status_code, 404, flag)
        second = Client(enforce_csrf_checks=True)
        self.assertEqual(self.verify(client=second, second=True).status_code, 200)
        self.assertNotContains(self.get(client=second), 'id="preparation-form"')
        self.assertEqual(self.get("preparation", client=second).status_code, 403)
        self.assertEqual(self.command("RECORD", client=second).status_code, 403)
        self.assertEqual(self.post("preparation", {"command": "RECORD", "request_key": None,
                                                  "code": "other-school"}).status_code, 400)
        self.assertEqual(self.command("QUEUE", "not-a-uuid").status_code, 400)
        payload = asdict(self.candidate)
        with self.assertRaises(PermissionDenied):
            record_synthetic_setup_intent(operator=self.operator, payload=payload, privileged=True)
        with self.assertRaises(PermissionDenied):
            advance_synthetic_preparation(
                operator=self.operator, payload=payload, command="QUEUE", request_key=uuid4(), privileged=True,
            )
        with self.assertRaises(PermissionDenied):
            provision_synthetic_inactive_school(
                proposer=self.operator, approver=self.second, payload=payload,
                proposal_proof_id=uuid4(), approval_proof_id=uuid4(),
                authorization_reference="SYNTHETIC-TEST",
            )
        revoke_registered_operator_credential(operator=self.operator, credential_id_digest=self.digest)
        self.assertEqual(self.get("preparation").status_code, 403)
        self.assertEqual(self.command("RECORD").status_code, 403)
        self.assertFalse(SchoolSetupIntent.objects.exists())
        self.assertFalse(SchoolPreparationEvent.objects.exists())
        self.assertFalse(School.objects.exists())
