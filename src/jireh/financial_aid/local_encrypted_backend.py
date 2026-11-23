"""Preproduction-only encrypted, private, local document backend.

This implements the SyntheticDocumentBackend interface for fictional data.
It is not a substitute for production-grade key management, retention,
malware scan operations, encrypted backups or a reviewed hosting decision.

The storage root must already exist, belong to this process, and have mode
0700. Only canonical random UUID object keys are accepted. No public URLs.
All file creation is exclusive; ciphertext is bound to its object key by AAD.
"""
import os
import stat
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .clamav_instream import ClamdInstreamScanner


_HEADER = b"JIREH-DOC-AESGCM-V1\x00"
_NONCE_BYTES = 12
_MAX_PLAINTEXT = 20 * 1024 * 1024


class PrivateDocumentStorageError(ValueError):
    """Constant non-sensitive error code; never includes object keys or paths."""


def _reject(code):
    raise PrivateDocumentStorageError(code)


class LocalEncryptedClamdBackend:
    """Locked-down, testable encrypted object store for local preproduction.

    ClamAV must be separately installed, configured, and managed. A clean
    result is required before an object is written; scanning is not a
    substitute for an operational review or sandbox.
    """

    synthetic_only = True
    private_storage = True
    encrypted_storage = True

    def __init__(self, *, root, encryption_key, scanner, max_bytes=10 * 1024 * 1024):
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            _reject("private_storage_platform_unsupported")
        if not isinstance(root, (str, Path)):
            _reject("private_storage_root_invalid")
        if type(encryption_key) is not bytes or len(encryption_key) != 32:
            _reject("private_storage_key_invalid")
        if (
            type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_PLAINTEXT
            or not callable(getattr(scanner, "scan", None))
        ):
            _reject("private_storage_policy_invalid")
        self._root = os.fspath(root)
        if not self._root or not os.path.isabs(self._root):
            _reject("private_storage_root_invalid")
        self._key = encryption_key
        self._scanner = scanner
        self._max_bytes = max_bytes
        # Validate at construction and again for every operation.
        self._open_root().close()

    def _open_root(self):
        try:
            fd = os.open(
                self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            metadata = os.fstat(fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.geteuid()
            ):
                os.close(fd)
                _reject("private_storage_root_not_private")
            return _RootHandle(fd)
        except OSError:
            _reject("private_storage_root_not_private")

    @staticmethod
    def _key_name(object_key):
        if type(object_key) is not str:
            _reject("private_storage_key_name_invalid")
        try:
            identifier = uuid.UUID(object_key)
        except (TypeError, AttributeError, ValueError):
            _reject("private_storage_key_name_invalid")
        if str(identifier) != object_key:
            _reject("private_storage_key_name_invalid")
        return identifier.hex + ".jenc"

    @staticmethod
    def _aad(object_key):
        return b"jireh:synthetic-document:v1:" + object_key.encode("ascii")

    @staticmethod
    def _media_type(data):
        # A small, conservative signature gate. ClamAV handles malware
        # verdicts; this signature check is not a comprehensive PDF parser.
        if (
            data.startswith(b"%PDF-")
            and len(data) >= 14
            and b"%%EOF" in data[-1024:]
        ):
            return "application/pdf"
        return "application/octet-stream"

    def inspect(self, data):
        if type(data) is not bytes or not 0 < len(data) <= self._max_bytes:
            _reject("private_storage_input_rejected")
        # Scanner errors intentionally propagate: no clean result means no put.
        clean = self._scanner.scan(data)
        if clean is not True:
            return self._media_type(data), False
        return self._media_type(data), True

    def put(self, object_key, data):
        filename = self._key_name(object_key)
        if type(data) is not bytes or not 0 < len(data) <= self._max_bytes:
            _reject("private_storage_input_rejected")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, data, self._aad(object_key)
        )
        payload = _HEADER + nonce + ciphertext
        with self._open_root() as directory:
            try:
                fd = os.open(
                    filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory.fd,
                )
            except FileExistsError:
                _reject("private_storage_object_exists")
            except OSError:
                _reject("private_storage_write_failed")
            try:
                with os.fdopen(fd, "wb", closefd=True) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory.fd)
            except Exception:
                try:
                    os.unlink(filename, dir_fd=directory.fd)
                except OSError:
                    pass
                _reject("private_storage_write_failed")

    def get(self, object_key):
        filename = self._key_name(object_key)
        with self._open_root() as directory:
            try:
                fd = os.open(
                    filename, os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=directory.fd,
                )
            except OSError:
                _reject("private_storage_read_failed")
            try:
                metadata = os.fstat(fd)
                upper_bound = (
                    len(_HEADER) + _NONCE_BYTES + self._max_bytes + 16
                )
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1
                    or metadata.st_size > upper_bound
                ):
                    _reject("private_storage_object_invalid")
                with os.fdopen(fd, "rb", closefd=True) as stream:
                    fd = -1
                    payload = stream.read(upper_bound + 1)
            finally:
                if fd != -1:
                    os.close(fd)
        if (
            len(payload) < len(_HEADER) + _NONCE_BYTES + 16
            or len(payload) > upper_bound
            or not payload.startswith(_HEADER)
        ):
            _reject("private_storage_object_invalid")
        nonce = payload[len(_HEADER):len(_HEADER) + _NONCE_BYTES]
        ciphertext = payload[len(_HEADER) + _NONCE_BYTES:]
        try:
            return AESGCM(self._key).decrypt(
                nonce, ciphertext, self._aad(object_key)
            )
        except (InvalidTag, ValueError):
            _reject("private_storage_authentication_failed")

    def delete(self, object_key):
        filename = self._key_name(object_key)
        with self._open_root() as directory:
            try:
                os.unlink(filename, dir_fd=directory.fd)
                os.fsync(directory.fd)
            except FileNotFoundError:
                return  # Idempotent retry after successful prior deletion.
            except OSError:
                _reject("private_storage_delete_failed")


class _RootHandle:
    def __init__(self, fd):
        self.fd = fd

    def close(self):
        os.close(self.fd)
        self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
