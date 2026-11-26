"""Opt-in disposable HTTPS browser acceptance; invoked explicitly in CI."""
import base64
import hashlib
import http.client
import socket
import ssl
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from socketserver import ThreadingMixIn
from unittest.mock import patch
from uuid import uuid4
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.core.wsgi import get_wsgi_application
from django.db import connections
from django.test import override_settings
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from .models import OperatorWebAuthnCredential, School, SyntheticSchoolProvisioningReceipt
from .school_setup_preflight import SchoolSetupCandidate
from .test_operator_portal import OperatorPortalTests
from .test_operator_webauthn_registry import CREDENTIAL_ID, PASSWORD

_RP = "operations.jireh.test"
_ORIGIN = f"https://{_RP}"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        pass


class _ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


@contextmanager
def _https_server(rp=_RP):
    """Pin only this run's certificate, and bind exclusively to loopback."""
    with tempfile.TemporaryDirectory(prefix="jireh-https-browser-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", f"/CN={rp}", "-addext", f"subjectAltName=DNS:{rp}",
            "-keyout", str(key), "-out", str(cert),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        app = get_wsgi_application()

        def secure_app(environ, start_response):
            environ["wsgi.url_scheme"] = "https"
            environ["HTTPS"] = "on"
            return app(environ, start_response)

        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        spki = x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        pin = base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
        with make_server("127.0.0.1", 0, secure_app, server_class=_ThreadedServer,
                         handler_class=_QuietHandler) as server:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield server.server_port, pin, cert
            finally:
                server.shutdown()
                thread.join(timeout=5)


def _database_readback(action):
    """Django ORM cannot execute on Playwright's active event-loop thread."""
    def run():
        try:
            return action()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result(timeout=30)


@override_settings(ALLOWED_HOSTS=[_RP], JIREH_OPERATOR_PORTAL_RP_ID=_RP)
class OperatorBrowserAcceptance(OperatorPortalTests):
    def setUp(self):
        # Change only the fictional fixture constants, never the verifier.
        for module in ("test_operator_webauthn_registry", "test_first_director_mfa", "test_operator_portal"):
            patcher = patch.multiple(f"jireh.schools.{module}", RP=_RP, ORIGIN=_ORIGIN)
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()

    def test_https_fixture_boundary(self):
        with _https_server() as (port, _, cert):
            tls = ssl.create_default_context(cafile=str(cert))
            with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
                with tls.wrap_socket(raw, server_hostname=_RP) as secure:
                    secure.sendall(f"GET /operations/ HTTP/1.1\r\nHost: {_RP}\r\nConnection: close\r\n\r\n".encode())
                    response = http.client.HTTPResponse(secure)
                    response.begin()
                    self.assertEqual(response.status, 200)
                    content = response.read()
                    self.assertIn(b"Operator sign-in", content)
                    self.assertNotIn(self.payload["name"].encode(), content)
                    self.assertIn("no-store", response.getheader("Cache-Control"))

    def test_operator_browser(self):
        from playwright.sync_api import expect, sync_playwright

        candidate = SchoolSetupCandidate(
            "synthetic-browser-preparation", "Synthetic Browser Preparation",
            "America/New_York", str(uuid4()),
        )
        self.enterContext(self.settings(
            JIREH_OPERATOR_PREPARATION_ACCEPTANCE=True,
            JIREH_OPERATOR_PREPARATION_FIXTURE=(self.operator.pk, candidate),
        ))
        conflict = School.objects.create(code=candidate.code, name="Fictional conflict", is_active=False)
        with _https_server() as (port, pin, _), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=[
                "--no-proxy-server",
                f"--host-resolver-rules=MAP {_RP}:443 127.0.0.1:{port}, MAP * ~NOTFOUND",
                f"--ignore-certificate-errors-spki-list={pin}",
            ])
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", lambda route: route.continue_()
                              if route.request.url.startswith(_ORIGIN + "/") else route.abort())
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                home = _ORIGIN + "/operations/"
                self.assertEqual(page.goto(home).status, 200)
                self.assertTrue(page.evaluate("window.isSecureContext"))
                expect(page.get_by_role("heading", name="Operator sign-in")).to_be_visible()
                expect(page.get_by_text(self.payload["name"], exact=True)).to_have_count(0)
                expect(page.get_by_role("heading", name="School preparation status")).to_have_count(0)
                page.get_by_label("Username").fill(self.operator.username)
                page.get_by_label("Password").fill(PASSWORD)
                page.get_by_role("button", name="Continue to security key").click()
                expect(page.get_by_role("heading", name="Verify operator security key")).to_be_visible(timeout=15000)
                expect(page.get_by_text(self.payload["name"], exact=True)).to_have_count(0)
                expect(page.get_by_role("heading", name="School preparation status")).to_have_count(0)
                count = _database_readback(lambda: OperatorWebAuthnCredential.objects.values_list(
                    "sign_count", flat=True).get(pk=self.credential.pk))
                cdp = context.new_cdp_session(page)
                cdp.send("WebAuthn.enable")
                authenticator = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
                    "protocol": "ctap2", "transport": "usb", "hasResidentKey": False,
                    "hasUserVerification": True, "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }})["authenticatorId"]
                private = self.key.private_bytes(serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
                cdp.send("WebAuthn.addCredential", {"authenticatorId": authenticator, "credential": {
                    "credentialId": base64.b64encode(CREDENTIAL_ID).decode(), "isResidentCredential": False,
                    "rpId": _RP, "privateKey": base64.b64encode(private).decode(), "signCount": count,
                }})
                page.get_by_role("button", name="Verify security key").click()
                expect(page.get_by_role("heading", name="Verified school registry")).to_be_visible(timeout=15000)
                expect(page.get_by_text(self.payload["name"], exact=True)).to_be_visible()
                expect(page.get_by_text("Inactive fixture", exact=True)).to_be_visible()
                expect(page.get_by_role("heading", name="School preparation status")).to_be_visible()
                expect(page.locator("#preparation-total")).to_have_text("1")
                expect(page.locator('[data-preparation-state="PREPARED"] td')).to_have_text("1")
                expect(page.get_by_text(candidate.name, exact=True)).to_be_visible()
                page.get_by_role("button", name="Record fictional setup").click()
                expect(page.locator('[data-preparation-state="RECEIVED"] td')).to_have_text("1")
                page.get_by_role("button", name="Queue preflight").click()
                expect(page.locator('[data-preparation-state="QUEUED"] td')).to_have_text("1")
                page.get_by_role("button", name="Run preflight").click()
                expect(page.locator('[data-preparation-state="FAILED"] td')).to_have_text("1")
                expect(page.locator("#preparation-progress")).to_contain_text("Preflight failed.")
                expect(page.get_by_role("button", name="Retry preflight")).to_have_count(0)
                _database_readback(lambda: School.objects.filter(pk=conflict.pk).delete())
                page.reload()
                page.get_by_role("button", name="Retry preflight").click()
                expect(page.locator('[data-preparation-state="REQUEUED"] td')).to_have_text("1")
                page.get_by_role("button", name="Run preflight").click()
                expect(page.locator('[data-preparation-state="PREPARED"] td')).to_have_text("2")
                expect(page.get_by_role("button", name="Run preflight")).to_have_count(0)
                expect(page.get_by_role("button", name="Retry preflight")).to_have_count(0)
                self.assertGreater(_database_readback(lambda: OperatorWebAuthnCredential.objects.values_list(
                    "sign_count", flat=True).get(pk=self.credential.pk)), count)
                self.assertEqual(page.goto(_ORIGIN + "/operations/create/").status, 404)
                self.assertEqual(page.goto(_ORIGIN + "/operations/activate/").status, 404)
                self.assertEqual(page.goto(_ORIGIN + "/customer/").status, 404)
                page.goto(home)
                page.get_by_role("button", name="Sign out").click()
                expect(page.get_by_role("heading", name="Operator sign-in")).to_be_visible(timeout=15000)
                expect(page.get_by_text(self.payload["name"], exact=True)).to_have_count(0)
                expect(page.get_by_role("heading", name="School preparation status")).to_have_count(0)
                self.assertEqual(_database_readback(lambda: School.objects.count()), 1)
                self.assertEqual(_database_readback(lambda: SyntheticSchoolProvisioningReceipt.objects.count()), 1)
                self.assertFalse(_database_readback(lambda: School.objects.values_list(
                    "is_active", flat=True).get(pk=self.receipt.school_id)))
                self.assertFalse(errors, errors)
                print("PASS: authenticated operator browser, signed WebAuthn, registry, preparation failure and retry, closed routes and logout", flush=True)
            finally:
                browser.close()
