"""Isolated fake-data acceptance tests for local encrypted storage and ClamAV."""
import os
import socket
import struct
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from .clamav_instream import ClamdInstreamScanner, ClamdScanError
from .local_encrypted_backend import (
    LocalEncryptedClamdBackend, PrivateDocumentStorageError,
)


class FakeScanner:
    def __init__(self, response=True):
        self.response = response
        self.calls = []

    def scan(self, contents):
        self.calls.append(contents)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeClamdSocket:
    def __init__(self, reply):
        self.reply = reply
        self.sent = bytearray()
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, contents):
        self.sent.extend(contents)

    def recv(self, amount):
        if self.reply:
            response, self.reply = self.reply[:amount], self.reply[amount:]
            return response
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class ClamdInstreamTests(SimpleTestCase):
    def test_valid_loopback_instream_packet_and_explicit_clean_verdict(self):
        fake = FakeClamdSocket(b"stream: OK\0")
        scanner = ClamdInstreamScanner(
            loopback_host="127.0.0.1", port=3310, chunk_bytes=4,
        )
        with patch(
            "jireh.financial_aid.clamav_instream.socket.create_connection",
            return_value=fake,
        ) as create:
            self.assertTrue(scanner.scan(b"abcde"))
        create.assert_called_once_with(("127.0.0.1", 3310), timeout=10)
        self.assertEqual(
            bytes(fake.sent),
            b"zINSTREAM\0" + struct.pack("!I", 4) + b"abcd"
            + struct.pack("!I", 1) + b"e" + struct.pack("!I", 0),
        )

    def test_known_detection_does_not_return_clean(self):
        fake = FakeClamdSocket(b"stream: Eicar-Test-Signature FOUND\0")
        scanner = ClamdInstreamScanner(loopback_host="127.0.0.1", port=3310)
        with patch(
            "jireh.financial_aid.clamav_instream.socket.create_connection",
            return_value=fake,
        ):
            self.assertFalse(scanner.scan(b"%PDF-1.7\nfictional\n%%EOF"))

    def test_error_timeout_unrecognized_and_truncated_fail_closed(self):
        scanner = ClamdInstreamScanner(loopback_host="127.0.0.1", port=3310)
        for response in (
            b"", b"stream: ERROR\0", b"stream: OK",
            b"stream: OK\0EXTRA", b"stream: OK\0\0",
        ):
            with self.subTest(response=response):
                with patch(
                    "jireh.financial_aid.clamav_instream.socket.create_connection",
                    return_value=FakeClamdSocket(response),
                ):
                    with self.assertRaises(ClamdScanError):
                        scanner.scan(b"fictional bytes")
        with patch(
            "jireh.financial_aid.clamav_instream.socket.create_connection",
            side_effect=TimeoutError(),
        ):
            with self.assertRaisesRegex(ClamdScanError, "scanner_unavailable"):
                scanner.scan(b"fictional bytes")

    def test_invalid_endpoint_and_oversize_are_denied(self):
        for host in ("8.8.8.8", "localhost", "::ffff:8.8.8.8", None):
            with self.subTest(host=host):
                with self.assertRaises(ClamdScanError):
                    ClamdInstreamScanner(loopback_host=host, port=3310)
        for data in (b"", b"abcdef", None, "abc"):
            with self.subTest(data=data):
                scanner = ClamdInstreamScanner(
                    loopback_host="127.0.0.1", port=3310, max_bytes=5
                )
                with self.assertRaises(ClamdScanError):
                    scanner.scan(data)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX only")
class LocalEncryptedBackendTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.chmod(self.dir.name, 0o700)
        self.scanner = FakeScanner()
        self.key = os.urandom(32)
        self.backend = LocalEncryptedClamdBackend(
            root=Path(self.dir.name), encryption_key=self.key,
            scanner=self.scanner, max_bytes=4096,
        )
        self.uuid = str(uuid.uuid4())
        self.contents = b"%PDF-1.7\nfictional-family-data\n%%EOF"

    def tearDown(self):
        self.dir.cleanup()

    def test_real_authenticated_encryption_no_plaintext_and_round_trip(self):
        self.assertEqual(
            self.backend.inspect(self.contents),
            ("application/pdf", True),
        )
        self.backend.put(self.uuid, self.contents)
        files = list(Path(self.dir.name).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, uuid.UUID(self.uuid).hex + ".jenc")
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        ciphertext = files[0].read_bytes()
        self.assertNotIn(b"fictional-family-data", ciphertext)
        self.assertNotEqual(ciphertext, self.contents)
        self.assertEqual(self.backend.get(self.uuid), self.contents)
        self.backend.delete(self.uuid)
        self.backend.delete(self.uuid)
        self.assertFalse(list(Path(self.dir.name).iterdir()))

    def test_tamper_wrong_key_and_wrong_object_binding_fail_authentication(self):
        self.backend.put(self.uuid, self.contents)
        path = Path(self.dir.name) / (uuid.UUID(self.uuid).hex + ".jenc")
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(
            PrivateDocumentStorageError, "private_storage_authentication_failed"
        ):
            self.backend.get(self.uuid)
        path.write_bytes(bytes(data[:-1]) + bytes((data[-1] ^ 1,)))
        alternate = LocalEncryptedClamdBackend(
            root=self.dir.name, encryption_key=os.urandom(32),
            scanner=self.scanner,
        )
        with self.assertRaises(PrivateDocumentStorageError):
            alternate.get(self.uuid)
        another = str(uuid.uuid4())
        alternate_name = Path(self.dir.name) / (uuid.UUID(another).hex + ".jenc")
        alternate_name.write_bytes(path.read_bytes())
        os.chmod(alternate_name, 0o600)
        with self.assertRaises(PrivateDocumentStorageError):
            self.backend.get(another)

    def test_exclusive_object_creation_rejects_overwrite(self):
        self.backend.put(self.uuid, self.contents)
        with self.assertRaisesRegex(
            PrivateDocumentStorageError, "private_storage_object_exists"
        ):
            self.backend.put(self.uuid, self.contents + b"X")
        self.assertEqual(self.backend.get(self.uuid), self.contents)

    def test_root_privacy_and_symlink_traversal_are_denied(self):
        os.chmod(self.dir.name, 0o755)
        with self.assertRaises(PrivateDocumentStorageError):
            self.backend.put(self.uuid, self.contents)
        os.chmod(self.dir.name, 0o700)
        with tempfile.TemporaryDirectory() as outer:
            link = Path(outer) / "link"
            link.symlink_to(Path(self.dir.name), target_is_directory=True)
            with self.assertRaises(PrivateDocumentStorageError):
                LocalEncryptedClamdBackend(
                    root=str(link), encryption_key=self.key,
                    scanner=self.scanner,
                )
        for untrusted in ("../etc/passwd", str(uuid.uuid4()).upper(), "", "abc"):
            with self.subTest(key=untrusted):
                with self.assertRaises(PrivateDocumentStorageError):
                    self.backend.put(untrusted, self.contents)

    def test_rejects_unsafe_files_and_invalid_settings(self):
        path = Path(self.dir.name) / (uuid.UUID(self.uuid).hex + ".jenc")
        path.symlink_to(Path(self.dir.name) / "missing")
        with self.assertRaises(PrivateDocumentStorageError):
            self.backend.get(self.uuid)
        with self.assertRaises(PrivateDocumentStorageError):
            LocalEncryptedClamdBackend(
                root=self.dir.name, encryption_key=b"weak",
                scanner=self.scanner,
            )
        with self.assertRaises(PrivateDocumentStorageError):
            self.backend.put(str(uuid.uuid4()), b"x" * 5000)

    def test_scanner_refusal_and_detection_do_not_claim_clean(self):
        self.scanner.response = False
        self.assertEqual(
            self.backend.inspect(self.contents), ("application/pdf", False)
        )
        self.scanner.response = ClamdScanError("scanner_unavailable")
        with self.assertRaises(ClamdScanError):
            self.backend.inspect(self.contents)
        self.assertEqual(
            self.backend._media_type(b"<script>test</script>"),
            "application/octet-stream",
        )
