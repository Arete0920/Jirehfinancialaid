"""End-to-end disposable school-director password and signed MFA acceptance."""
import hashlib
import json
from datetime import date, timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from fido2.cose import ES256
from fido2.utils import sha256
from fido2.webauthn import (
    AttestedCredentialData, AuthenticationResponse, AuthenticatorAssertionResponse,
    AuthenticatorData, CollectedClientData, CredentialRequestOptions,
)

from jireh.financial_aid.services import get_or_create_annual_draft
from jireh.runtime.customer_director_sessions import DIRECTOR_SESSION_KEY
from jireh.schools.login_budget import MAX_LOGIN_ATTEMPTS
from jireh.schools.models import (
    AcademicYear, DirectorWebAuthnChallenge, DirectorWebAuthnCredential, Household,
    HouseholdAccess, School, SchoolStaffAccess,
)

RP = "director.jireh.example.invalid"
ORIGIN = "https://" + RP
PASSWORD = "Synthetic-Director-Password-01234!"
CREDENTIAL_ID = b"synthetic-director-http-key"


@override_settings(
    ROOT_URLCONF="jireh.runtime.customer_urls", ALLOWED_HOSTS=[RP, "testserver"],
    JIREH_CUSTOMER_CORE_ACCEPTANCE=True, JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE=True,
    JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE=True, JIREH_DIRECTOR_WEBAUTHN_RP_ID=RP,
    JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE=True,
    JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE=True, JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE=True,
    DEBUG=False, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True, SECURE_SSL_REDIRECT=True,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE=False, JIREH_SYNTHETIC_SUBMISSION_ONLY=False,
    JIREH_SYNTHETIC_DOCUMENTS_ONLY=False, JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE=False,
    JIREH_SYNTHETIC_APPLICATION_REVIEW=False, JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED=False,
)
class DirectorSessionTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.actor = users.create_user(username="director-http", password=PASSWORD)
        self.parent = users.create_user(username="parent-http", password=PASSWORD)
        self.admin = users.create_superuser(username="operator-http", password=PASSWORD)
        self.school = School.objects.create(code="director-http-a", name="Fictional A")
        self.other_school = School.objects.create(code="director-http-b", name="Fictional B")
        self.year = AcademicYear.objects.create(school=self.school, name="2026-27",
                                               start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        self.other_year = AcademicYear.objects.create(school=self.other_school, name="2026-27",
                                                     start_date=date(2026, 8, 1), end_date=date(2027, 6, 30))
        self.household = Household.objects.create(school=self.school, name="Fictional family")
        HouseholdAccess.objects.create(household=self.household, user=self.parent)
        self.draft = get_or_create_annual_draft(user=self.parent, school_id=self.school.pk,
                                                household_id=self.household.pk, academic_year_id=self.year.pk)
        self.grant = SchoolStaffAccess.objects.create(school=self.school, user=self.actor,
                                                     role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        SchoolStaffAccess.objects.create(school=self.other_school, user=self.actor,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        SchoolStaffAccess.objects.create(school=self.school, user=self.admin,
                                         role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.digest = hashlib.sha256(CREDENTIAL_ID).hexdigest()
        self.credential = DirectorWebAuthnCredential.objects.create(
            grant=self.grant, credential_id_digest=self.digest, rp_id=RP,
            credential_data=bytes(AttestedCredentialData.create(bytes(16), CREDENTIAL_ID,
                                  ES256.from_cryptography_key(self.key.public_key()))),
            enrollment_verified_at=timezone.now(),
        )

    def route(self, name, school=None):
        return reverse("jireh_customer_director_" + name, args=((school or self.school).pk,))

    def cases(self, school=None, year=None):
        return reverse("jireh_customer_cases", args=((school or self.school).pk, (year or self.year).pk))

    def get(self, client, url, **extra):
        return client.get(url, secure=True, HTTP_HOST=RP, **extra)

    def token(self, client):
        return self.get(client, self.route("login")).json()["csrf_token"]

    def post(self, client, url, data, token, **extra):
        return client.post(url, json.dumps(data), content_type="application/json", secure=True,
                           HTTP_HOST=RP, HTTP_ORIGIN=extra.pop("origin", ORIGIN),
                           HTTP_X_CSRFTOKEN=token, **extra)

    def password(self, client, user=None):
        return self.post(client, self.route("login"), {"username": (user or self.actor).username,
                         "password": PASSWORD}, self.token(client))

    def begin(self, client):
        response = self.post(client, self.route("begin"), {"credential_id_digest": self.digest}, self.token(client))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def signed(self, challenge, *, count=1, key=None, origin=ORIGIN):
        options = CredentialRequestOptions.from_dict(challenge["options"])
        client = CollectedClientData.create(CollectedClientData.TYPE.GET, options.public_key.challenge, origin)
        data = AuthenticatorData.create(sha256(RP.encode()), AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV, count)
        signature = (key or self.key).sign(bytes(data) + client.hash, ec.ECDSA(hashes.SHA256()))
        return {"challenge_id": challenge["challenge_id"], "assertion": dict(AuthenticationResponse(
            raw_id=CREDENTIAL_ID, response=AuthenticatorAssertionResponse(
                client_data=client, authenticator_data=data, signature=signature,
            ),
        ))}

    def verified(self, client):
        self.assertEqual(self.password(client).status_code, 200)
        challenge = self.begin(client)
        result = self.post(client, self.route("complete"), self.signed(challenge), self.token(client))
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def test_password_to_signed_director_readback_with_rotation_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.get(client, self.cases()).status_code, 403)
        response = self.password(client)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["authenticated"])
        self.assertTrue(response.json()["verification_required"])
        self.assertEqual(response.json()["credential_refs"], [self.digest])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(client.cookies["sessionid"]["secure"])
        self.assertTrue(client.cookies["sessionid"]["httponly"])
        self.assertLessEqual(client.session.get_expiry_age(), 300)
        self.assertEqual(self.get(client, self.cases()).status_code, 403)
        household = reverse("jireh_customer_household", args=(self.school.pk, self.household.pk))
        self.assertEqual(self.get(client, household).status_code, 403)
        # A valid family grant cannot turn a director password stage into a family session.
        HouseholdAccess.objects.create(household=self.household, user=self.actor)
        self.assertEqual(self.get(client, household).status_code, 403)
        old_key = client.session.session_key
        challenge = self.begin(client)
        data = self.signed(challenge)
        old_csrf = self.token(client)
        result = self.post(client, self.route("complete"), data, old_csrf)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()["authenticated"])
        self.assertNotEqual(client.session.session_key, old_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertLessEqual(client.session.get_expiry_age(), 900)
        self.assertEqual(client.session[DIRECTOR_SESSION_KEY]["stage"], "verified")
        self.assertEqual(self.get(client, self.cases()).json()["applications"][0]["id"], str(self.draft.pk))
        self.assertEqual(self.get(client, self.cases() + str(self.draft.pk) + "/").json()["application_id"], str(self.draft.pk))
        self.assertEqual(self.get(client, self.cases(self.other_school, self.other_year)).status_code, 403)
        self.assertEqual(self.get(client, household).status_code, 403)
        self.assertEqual(self.post(client, self.route("complete"), data, result.json()["csrf_token"]).status_code, 403)
        key = client.session.session_key
        self.assertEqual(self.post(client, self.route("logout"), {}, old_csrf).status_code, 403)
        self.assertEqual(self.post(client, self.route("logout"), {}, result.json()["csrf_token"]).status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(self.get(client, self.cases()).status_code, 403)

    def test_raw_session_and_privileged_accounts_cannot_bypass_mfa(self):
        for user in (self.actor, self.admin):
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            self.assertEqual(self.get(client, self.cases()).status_code, 403)
            self.assertEqual(self.post(client, self.route("begin"), {"credential_id_digest": self.digest}, self.token(client)).status_code, 403)
        for user in (self.admin, self.parent):
            self.assertEqual(self.password(Client(enforce_csrf_checks=True), user).status_code, 401)
        # The ordinary family session cannot start the director flow.
        client = Client(enforce_csrf_checks=True)
        url = reverse("jireh_customer_family_login")
        self.assertEqual(self.post(client, url, {"username": self.parent.username, "password": PASSWORD},
                                   self.get(client, url).json()["csrf_token"]).status_code, 200)
        self.assertEqual(self.get(client, self.route("login")).status_code, 403)
        self.assertEqual(self.get(client, self.cases()).status_code, 403)

    def test_cross_session_and_wrong_school_proof_cannot_be_consumed(self):
        first, second = Client(enforce_csrf_checks=True), Client(enforce_csrf_checks=True)
        self.assertEqual(self.password(first).status_code, 200)
        self.assertEqual(self.password(second).status_code, 200)
        challenge = self.begin(first)
        data = self.signed(challenge)
        self.assertEqual(self.post(second, self.route("complete"), data, self.token(second)).status_code, 403)
        self.assertEqual(self.post(first, self.route("complete", self.other_school), data, self.token(first)).status_code, 403)
        self.assertIsNone(DirectorWebAuthnChallenge.objects.get(pk=challenge["challenge_id"]).closed_at)
        self.assertEqual(self.post(first, self.route("complete"), data, self.token(first)).status_code, 200)
        self.assertEqual(self.get(second, self.cases()).status_code, 403)

    def test_wrong_signature_origin_csrf_and_bounded_attempt_budget(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.password(client).status_code, 200)
        challenge = self.begin(client)
        data = self.signed(challenge, key=ec.generate_private_key(ec.SECP256R1()))
        token = self.token(client)
        self.assertEqual(self.post(client, self.route("complete"), data, token, origin="https://evil.example.invalid").status_code, 403)
        self.assertIsNone(DirectorWebAuthnChallenge.objects.get(pk=challenge["challenge_id"]).closed_at)
        self.assertEqual(self.post(client, self.route("complete"), data, token).status_code, 403)
        self.assertIsNotNone(DirectorWebAuthnChallenge.objects.get(pk=challenge["challenge_id"]).closed_at)
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.sign_count, 0)
        self.assertEqual(self.get(client, self.cases()).status_code, 403)
        for _ in range(MAX_LOGIN_ATTEMPTS - 2):
            self.assertEqual(self.post(client, self.route("begin"), {}, token).status_code, 400)
        limited = self.post(client, self.route("begin"), {"credential_id_digest": self.digest}, token)
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited["Retry-After"]), 0)

    def test_verified_session_revocation_and_expiration(self):
        client = Client(enforce_csrf_checks=True)
        self.verified(client)
        self.assertEqual(self.get(client, self.cases()).status_code, 200)
        with patch("jireh.runtime.customer_director_sessions.timezone.now", return_value=timezone.now() + timedelta(minutes=16)):
            self.assertEqual(self.get(client, self.cases()).status_code, 403)
        self.grant.is_active = False
        self.grant.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.get(client, self.cases()).status_code, 403)
        self.grant.is_active = True
        self.grant.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.get(client, self.cases()).status_code, 403)
        # A separate clean session is denied immediately on credential revocation.
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.password(client).status_code, 200)
        challenge = self.begin(client)
        self.assertEqual(self.post(client, self.route("complete"), self.signed(challenge, count=2), self.token(client)).status_code, 200)
        self.credential.refresh_from_db()
        self.credential.revoked_at = timezone.now()
        self.credential.save(update_fields=["revoked_at", "updated_at"])
        self.assertEqual(self.get(client, self.cases()).status_code, 403)

    def test_settings_host_pending_expiry_and_database_failure(self):
        client = Client(enforce_csrf_checks=True)
        for values in ({"JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE": False},
                       {"JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE": False},
                       {"SETTINGS_MODULE": "jireh.runtime.settings"},
                       {"CSRF_COOKIE_HTTPONLY": False}):
            with self.settings(**values):
                self.assertEqual(self.get(client, self.route("login")).status_code, 404)
        self.assertEqual(client.get(self.route("login"), secure=True, HTTP_HOST="testserver").status_code, 404)
        login_url = self.route("login")
        with self.settings(ROOT_URLCONF="jireh.runtime.urls"):
            self.assertEqual(self.get(client, login_url).status_code, 404)
        self.assertEqual(self.password(client).status_code, 200)
        token = self.token(client)
        with patch("jireh.runtime.customer_director_sessions.charge_director_assertion_attempt", side_effect=DatabaseError("private")):
            response = self.post(client, self.route("begin"), {}, token)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.content.decode())
        with patch("jireh.runtime.customer_director_sessions.timezone.now", return_value=timezone.now() + timedelta(minutes=6)):
            self.assertEqual(self.post(client, self.route("begin"), {"credential_id_digest": self.digest}, token).status_code, 403)
