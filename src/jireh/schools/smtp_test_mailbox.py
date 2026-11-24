"""Disposable loopback SMTP peer for the authenticated delivery rehearsal."""

import base64
import hmac
import os
import socket
import socketserver
import ssl
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import override_settings


_HOST = "smtp-rehearsal.example.invalid"
_PORT = 465
_USERNAME = "fictional-mail-user"
_PASSWORD = "fictional-mail-password"
SMTP_SENDER = "fictional-school@example.invalid"
_AUTH_PLAIN = b"PLAIN " + base64.b64encode(f"\0{_USERNAME}\0{_PASSWORD}".encode("ascii"))
_SOCKET_TIMEOUT = 5


@dataclass(frozen=True)
class _Delivery:
    sender: str
    recipient: str
    tls_version: str | None
    message: bytes = field(repr=False)


class _SmtpHandler(socketserver.StreamRequestHandler):
    def _reply(self, *lines):
        self.wfile.write(b"\r\n".join(lines) + b"\r\n")

    def _read_message(self):
        message = bytearray()
        while line := self.rfile.readline(4097):
            if line == b".\r\n":
                return bytes(message)
            if not line.endswith(b"\r\n") or len(message) + len(line) > 16_384:
                raise ValueError("Invalid rehearsal message framing.")
            message.extend(line[1:] if line.startswith(b"..") else line)
        raise EOFError("Rehearsal message ended before its SMTP terminator.")

    def handle(self):
        authenticated = False
        sender = recipient = None
        self._reply(b"220 loopback SMTP rehearsal")
        for _ in range(12):
            line = self.rfile.readline(4097)
            if not line:
                return
            verb, _, argument = line.rstrip(b"\r\n").partition(b" ")
            verb = verb.upper()
            if verb == b"EHLO":
                self._reply(b"250-loopback", b"250 AUTH PLAIN")
            elif verb == b"AUTH":
                authenticated = hmac.compare_digest(argument, _AUTH_PLAIN)
                self._reply(b"235 Authentication successful" if authenticated else b"535 Authentication rejected")
            elif verb == b"MAIL" and authenticated and argument.upper().startswith(b"FROM:"):
                sender = argument[5:].strip(b"<>").decode("ascii")
                recipient = None
                self._reply(b"250 Sender accepted")
            elif verb == b"RCPT" and sender and argument.upper().startswith(b"TO:"):
                recipient = argument[3:].strip(b"<>").decode("ascii")
                self._reply(b"250 Recipient accepted")
            elif verb == b"DATA" and authenticated and sender and recipient:
                self._reply(b"354 End with a line containing a single dot")
                message = self._read_message()
                self.server.deliveries.append(_Delivery(
                    sender, recipient, self.request.version(), message,
                ))
                self._reply(b"554 Message rejected for rehearsal" if self.server.reject_data else b"250 Message accepted")
                sender = recipient = None
            elif verb == b"RSET":
                sender = recipient = None
                self._reply(b"250 Reset")
            elif verb == b"QUIT":
                self._reply(b"221 Closing connection")
                return
            else:
                self._reply(b"503 Unexpected SMTP command")


class _MailboxServer(socketserver.TCPServer):
    def __init__(self, tls_context, reject_data):
        self.tls_context = tls_context
        self.reject_data = reject_data
        self.deliveries = []
        self.errors = []
        self.failed_handshakes = 0
        self._connection_lock = Lock()
        self._closing = False
        self._active_socket = None
        super().__init__(("127.0.0.1", 0), _SmtpHandler)

    def get_request(self):
        connection, address = super().get_request()
        try:
            connection.settimeout(_SOCKET_TIMEOUT)
            connection = self.tls_context.wrap_socket(
                connection, server_side=True, do_handshake_on_connect=False,
            )
            with self._connection_lock:
                if self._closing:
                    raise OSError("SMTP rehearsal is closing.")
                self._active_socket = connection
            connection.do_handshake()
            return connection, address
        except OSError as error:
            if isinstance(error, ssl.SSLError):
                self.failed_handshakes += 1
            self.shutdown_request(connection)
            raise

    def shutdown_request(self, request):
        super().shutdown_request(request)
        with self._connection_lock:
            if self._active_socket is request:
                self._active_socket = None

    def interrupt_active_connection(self):
        with self._connection_lock:
            self._closing = True
            connection = self._active_socket
        if connection is not None:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)

    def handle_error(self, request, client_address):
        if not self._closing:
            self.errors.append(type(sys.exception()).__name__)


def _test_certificate(directory, hostname):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = Path(directory) / "rehearsal.pem"
    key_path = Path(directory) / "rehearsal.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    return cert_path, key_path


@contextmanager
def tls_mailbox(*, reject_data=False, certificate_hostname=_HOST, trust_certificate=True):
    """Map one synthetic hostname to an ephemeral TLS SMTP socket."""
    with TemporaryDirectory(prefix="jireh-smtp-rehearsal-") as directory:
        cert_path, key_path = _test_certificate(directory, certificate_hostname)
        trust_path = cert_path
        if not trust_certificate:
            trust_path = Path(directory) / "empty-trust.pem"
            trust_path.touch()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_path, key_path)
        with _MailboxServer(context, reject_data) as server:
            def loopback_only(host, port, *_args, **_kwargs):
                if (host, port) != (_HOST, _PORT):
                    raise AssertionError("Unexpected network destination during SMTP rehearsal.")
                return [(
                    socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", server.server_address,
                )]

            worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            worker.start()
            try:
                with (
                    override_settings(
                        JIREH_EMAIL_DELIVERY_ENABLED=True,
                        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                        EMAIL_USE_TLS=False, EMAIL_USE_SSL=True,
                        EMAIL_HOST=_HOST, EMAIL_PORT=_PORT,
                        EMAIL_HOST_USER=_USERNAME, EMAIL_HOST_PASSWORD=_PASSWORD,
                        EMAIL_TIMEOUT=_SOCKET_TIMEOUT, JIREH_EMAIL_FROM=SMTP_SENDER,
                    ),
                    patch.object(socket, "getaddrinfo", loopback_only),
                    patch("django.core.mail.backends.smtp.DNS_NAME.get_fqdn", return_value="client.example.invalid"),
                    patch.dict(os.environ, {"SSL_CERT_FILE": str(trust_path), "SSLKEYLOGFILE": ""}),
                ):
                    yield server
            finally:
                server.interrupt_active_connection()
                server.shutdown()
                worker.join()
            if server.errors:
                raise AssertionError(f"SMTP rehearsal peer failed: {', '.join(server.errors)}")
