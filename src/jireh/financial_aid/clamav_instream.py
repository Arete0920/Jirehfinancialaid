"""Fail-closed ClamAV INSTREAM adapter for local preproduction document scans.

Only a local Unix socket or literal loopback TCP address is accepted.
ClamAV TCP is not encrypted or authenticated; never expose it to a network.
An OK reply proves only that the configured daemon returned OK at scan time.
"""
import ipaddress
import socket
import struct
import time


class ClamdScanError(ValueError):
    """Constant error code, never includes document content or daemon replies."""


class ClamdInstreamScanner:
    def __init__(
        self, *, unix_socket_path=None, loopback_host=None, port=None,
        timeout_seconds=10, max_bytes=10 * 1024 * 1024, chunk_bytes=64 * 1024,
    ):
        using_unix = type(unix_socket_path) is str and bool(unix_socket_path)
        using_tcp = loopback_host is not None or port is not None
        if using_unix == using_tcp:
            raise ClamdScanError("scanner_endpoint_invalid")
        if using_unix:
            if "\0" in unix_socket_path or len(unix_socket_path) > 103:
                raise ClamdScanError("scanner_endpoint_invalid")
        else:
            try:
                address = ipaddress.ip_address(loopback_host)
            except (ValueError, TypeError):
                raise ClamdScanError("scanner_endpoint_invalid") from None
            if not address.is_loopback or type(port) is not int or not 1 <= port <= 65535:
                raise ClamdScanError("scanner_endpoint_invalid")
        if (
            type(timeout_seconds) not in (float, int)
            or not 0 < timeout_seconds <= 60
            or type(max_bytes) is not int or not 1 <= max_bytes <= 20 * 1024 * 1024
            or type(chunk_bytes) is not int or not 1 <= chunk_bytes <= 1024 * 1024
        ):
            raise ClamdScanError("scanner_limits_invalid")
        self._unix_socket_path = unix_socket_path if using_unix else None
        self._loopback_host = loopback_host if using_tcp else None
        self._port = port
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._chunk_bytes = chunk_bytes

    def scan(self, contents: bytes) -> bool:
        """True: clean; False: detection; raises: scanner unavailable/uncertain."""
        if (
            type(contents) is not bytes
            or not contents
            or len(contents) > self._max_bytes
        ):
            raise ClamdScanError("scanner_input_rejected")
        deadline = time.monotonic() + self._timeout

        def remaining(connection=None):
            left = deadline - time.monotonic()
            if left <= 0:
                raise ClamdScanError("scanner_unavailable")
            if connection is not None:
                connection.settimeout(left)
            return left

        try:
            if self._unix_socket_path is not None:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(remaining())
                try:
                    connection.connect(self._unix_socket_path)
                except Exception:
                    connection.close()
                    raise
            else:
                connection = socket.create_connection(
                    (self._loopback_host, self._port), timeout=remaining()
                )
            with connection:
                remaining(connection)
                connection.sendall(b"zINSTREAM\0")
                remaining()
                for i in range(0, len(contents), self._chunk_bytes):
                    chunk = contents[i:i + self._chunk_bytes]
                    remaining(connection)
                    connection.sendall(struct.pack("!I", len(chunk)))
                    remaining(connection)
                    connection.sendall(chunk)
                    remaining()
                remaining(connection)
                connection.sendall(struct.pack("!I", 0))
                remaining()
                reply = bytearray()
                while b"\0" not in reply:
                    remaining(connection)
                    chunk = connection.recv(256)
                    remaining()
                    if not chunk:
                        raise ClamdScanError("scanner_result_incomplete")
                    reply.extend(chunk)
                    if len(reply) > 256:
                        raise ClamdScanError("scanner_result_invalid")
        except (OSError, TimeoutError) as exc:
            raise ClamdScanError("scanner_unavailable") from None
        if reply.count(0) != 1 or reply[-1] != 0:
            raise ClamdScanError("scanner_result_invalid")
        payload = bytes(reply[:-1])
        if payload == b"stream: OK":
            return True
        if payload.startswith(b"stream: ") and payload.endswith(b" FOUND"):
            if len(payload) > len(b"stream:  FOUND"):
                return False
        raise ClamdScanError("scanner_result_invalid")
