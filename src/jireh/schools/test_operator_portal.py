"""Disposable acceptance of MFA-protected read-only school operations."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from fido2.webauthn import PublicKeyCredentialRequestOptions

from jireh.runtime.operator_portal import SESSION_KEY
from .demo_setup_intents import record_synthetic_setup_intent
from .models import OperatorWebAuthnChallenge, School, SyntheticSchoolProvisioningReceipt
from .operator_webauthn_registry import revoke_registered_operator_credential
from .test_first_director_mfa import FirstDirectorProofFixture
from .test_onboarding_rehearsal import FictionalOnboardingRehearsal
from .test_operator_webauthn_registry import CREDENTIAL_ID, ORIGIN, PASSWORD, RP
from . import test_synthetic_provisioning as provisioning_fixtures


@override_settings(
    ROOT_URLCONF="jireh.runtime.operator_portal_urls", ALLOWED_HOSTS=[RP, "testserver"],
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}],
    JIREH_OPERATOR_PORTAL_ACCEPTANCE=True, JIREH_OPERATOR_PORTAL_RP_ID=RP,
    JIREH_SYNTHETIC_SETUP_INTENT_ONLY=True, JIREH_SYNTHETIC_PREPARATION_JOB_ONLY=True,
    JIREH_SYNTHETIC_PROVISIONING_ONLY=True, JIREH_SCHOOL_SETUP_ACTION_MFA_ENABLED=True,
    JIREH_SYNTHETIC_SUBMISSION_ONLY=False, JIREH_SYNTHETIC_DOCUMENTS_ONLY=False,
    JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False, DEBUG=False,
    SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
)
class OperatorPortalTests(FirstDirectorProofFixture, FictionalOnboardingRehearsal, TransactionTestCase):
    prepare = provisioning_fixtures.SyntheticProvisioningTests.prepare
    proofs = provisioning_fixtures.SyntheticProvisioningTests.proofs
    setup_proof = provisioning_fixtures.SyntheticProvisioningTests.setup_proof
    execute = provisioning_fixtures.SyntheticProvisioningTests.execute

    def setUp(self):
        super().setUp()
        self.enterContext(self.settings(JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED=False))
        self.payload = {"code": "synthetic-portal-academy", "name": "Synthetic Portal Academy",
                        "timezone": "America/New_York", "idempotency_key": str(uuid4())}
        # The existing provisioning fixture service remains inaccessible from
        # the independent operations router. Seed its fictional receipt here.
        with self.settings(ROOT_URLCONF="jireh.schools.urls"):
            self.setup = record_synthetic_setup_intent(operator=self.operator, payload=self.payload, privileged=True)
            self.prepare()
            self.receipt = self.execute(self.proofs())
        self.client = Client(enforce_csrf_checks=True)

    def get(self, name="home", client=None, **kwargs):
        return (client or self.client).get(reverse("jireh_operator_" + name), secure=True,
                                           HTTP_HOST=RP, **kwargs)

    def post(self, name, body, *, client=None, csrf=True, **kwargs):
        client = client or self.client
        if csrf:
            kwargs["HTTP_X_CSRFTOKEN"] = self.get("login", client=client).json()["csrf_token"]
        return client.post(reverse("jireh_operator_" + name), body, content_type="application/json",
                           secure=True, HTTP_HOST=RP, HTTP_ORIGIN=ORIGIN, **kwargs)

    def login(self, *, client=None, user=None):
        return self.post("login", {"username": (user or self.operator).username,
                                   "password": PASSWORD}, client=client)

    def begin_portal(self, *, client=None, digest=None):
        response = self.post("begin", {"credential_id_digest": digest or self.digest}, client=client)
        self.assertEqual(response.status_code, 200, response.content)
        return PublicKeyCredentialRequestOptions.from_dict(response.json()["options"]["publicKey"])

    def assertion_for(self, options, *, second=False, count=2):
        # The fixture's earlier setup action already used counter 1.
        from types import SimpleNamespace
        return dict(self.signed(SimpleNamespace(public_key=options),
                                key=self.second_key if second else self.key,
                                credential_id=self.second_key_id if second else CREDENTIAL_ID, count=count))

    def verify(self, *, client=None, second=False, count=2):
        client = client or self.client
        self.assertEqual(self.login(client=client, user=self.second if second else self.operator).status_code, 200)
        options = self.begin_portal(client=client, digest=self.second_digest if second else self.digest)
        return self.post("complete", {"assertion": self.assertion_for(options, second=second, count=count)}, client=client)

    def test_real_signed_assertion_reads_verified_registry_only(self):
        page = self.get()
        self.assertContains(page, "Operator sign-in")
        self.assertNotContains(page, self.payload["name"])
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", page["Content-Security-Policy"])
        self.assertEqual(self.login().status_code, 200)
        pending = self.get()
        self.assertContains(pending, "Verify operator security key")
        self.assertNotContains(pending, self.payload["name"])
        options = self.begin_portal()
        key_before = self.client.session.session_key
        result = self.post("complete", {"assertion": self.assertion_for(options)})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertNotEqual(self.client.session.session_key, key_before)
        registry = self.get()
        self.assertContains(registry, self.payload["name"])
        self.assertContains(registry, "Inactive fixture")
        self.assertContains(registry, "SCHOOL_INACTIVE")
        self.assertNotContains(registry, self.digest)
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(SyntheticSchoolProvisioningReceipt.objects.count(), 1)
        self.assertFalse(School.objects.get(pk=self.receipt.school_id).is_active)
        self.assertEqual(self.post("complete", {"assertion": self.assertion_for(options)}).status_code, 403)
        self.assertEqual(self.post("logout", {}).status_code, 200)
        self.assertNotContains(self.get(), self.payload["name"])

    def test_unmarked_other_session_bad_signature_and_revocation(self):
        self.client.force_login(self.operator)
        self.assertNotContains(self.get(), self.payload["name"])
        self.client.logout()
        self.assertEqual(self.login().status_code, 200)
        options = self.begin_portal()
        other = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client=other).status_code, 200)
        self.assertEqual(self.post("complete", {"assertion": self.assertion_for(options)}, client=other).status_code, 403)
        self.assertNotContains(self.get(client=other), self.payload["name"])
        self.assertEqual(self.post("complete", {"assertion": self.assertion_for(options, second=True)}).status_code, 403)
        proof = OperatorWebAuthnChallenge.objects.get(pk=self.client.session[SESSION_KEY]["challenge"])
        self.assertIsNotNone(proof.closed_at)
        self.assertIsNone(proof.verified_at)
        options = self.begin_portal()
        self.assertEqual(self.post("complete", {"assertion": self.assertion_for(options)}).status_code, 200)
        self.assertContains(self.get(), self.payload["name"])
        revoke_registered_operator_credential(operator=self.operator, credential_id_digest=self.digest)
        self.assertNotContains(self.get(), self.payload["name"])
        outsider = get_user_model().objects.create_superuser(username="unlisted-operator", password=PASSWORD)
        self.assertEqual(self.login(client=Client(enforce_csrf_checks=True), user=outsider).status_code, 401)

    def test_profile_guard_csrf_and_no_mutation_routes(self):
        self.assertEqual(self.post("login", {"username": self.operator.username, "password": PASSWORD}, csrf=False).status_code, 403)
        self.assertEqual(self.verify(second=True).status_code, 200)
        self.assertContains(self.get(), self.payload["name"])
        for values in ({"JIREH_OPERATOR_PORTAL_ACCEPTANCE": False}, {"JIREH_CUSTOMER_CORE_ACCEPTANCE": True},
                       {"JIREH_SYNTHETIC_SUBMISSION_ONLY": True}, {"JIREH_FIRST_DIRECTOR_BOOTSTRAP_ENABLED": True},
                       {"CSRF_COOKIE_HTTPONLY": False}, {"JIREH_SYNTHETIC_PROVISIONING_ONLY": False},
                       {"SETTINGS_MODULE": "jireh.runtime.settings"}, {"JIREH_OPERATOR_PORTAL_RP_ID": "wrong.invalid"}):
            with self.settings(**values):
                self.assertEqual(self.get().status_code, 404, values)
        self.assertEqual(self.client.get("/operations/", HTTP_HOST=RP).status_code, 404)
        for url in ("/operations/create/", "/operations/activate/", "/customer/", "/test-operations/schools/"):
            self.assertEqual(self.client.get(url, secure=True, HTTP_HOST=RP).status_code, 404)
        self.assertEqual(self.post("home", {}).status_code, 405)
        self.assertEqual(self.get(data={"school": str(self.receipt.school_id)}).status_code, 400)
        session = self.client.session
        session[SESSION_KEY] = {**session[SESSION_KEY], "binding": "0" * 64}
        session.save()
        self.assertNotContains(self.get(), self.payload["name"])

    def test_registry_integrity_failure_and_allowlist_removal(self):
        self.assertEqual(self.verify().status_code, 200)
        with self.settings(JIREH_BOOTSTRAP_OPERATOR_IDS=(self.second.pk, 999999)):
            self.assertNotContains(self.get(), self.payload["name"])
        School.objects.filter(pk=self.receipt.school_id).update(name="Synthetic changed identity")
        result = self.get()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(b"Synthetic changed identity", result.content)
