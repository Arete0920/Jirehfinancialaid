import unittest
from unittest.mock import patch
from jireh.financial_aid.clamav_instream import ClamdInstreamScanner, ClamdScanError


class DripReplySocket:
    def __init__(self, reply, clock, seconds_per_byte, seconds_per_send=0):
        self.reply = reply
        self.clock = clock
        self.seconds_per_byte = seconds_per_byte
        self.seconds_per_send = seconds_per_send
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, contents):
        self.clock[0] += self.seconds_per_send

    def recv(self, amount):
        self.clock[0] += self.seconds_per_byte
        if self.reply:
            result, self.reply = self.reply[:1], self.reply[1:]
            return result
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DeadlineTests(unittest.TestCase):
    def test_single_fast_clean_response_accepted(self):
        clock = [0.0]
        fake = DripReplySocket(b"stream: OK\0", clock, 0.01)
        scanner = ClamdInstreamScanner(loopback_host="127.0.0.1", port=3310, timeout_seconds=1)
        with patch("jireh.financial_aid.clamav_instream.socket.create_connection", return_value=fake), patch("time.monotonic", side_effect=lambda: clock[0]):
            self.assertTrue(scanner.scan(b"fictional"))

    def test_drip_reply_exceeding_total_deadline_fails_closed(self):
        clock = [0.0]
        fake = DripReplySocket(b"stream: OK\0", clock, 0.4)
        scanner = ClamdInstreamScanner(loopback_host="127.0.0.1", port=3310, timeout_seconds=1)
        with patch("jireh.financial_aid.clamav_instream.socket.create_connection", return_value=fake), patch("time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(ClamdScanError, "scanner_unavailable"):
                scanner.scan(b"fictional")

    def test_drip_upload_exceeding_total_deadline_fails_closed(self):
        clock = [0.0]
        fake = DripReplySocket(b"stream: OK\0", clock, 0.01, seconds_per_send=0.4)
        scanner = ClamdInstreamScanner(loopback_host="127.0.0.1", port=3310, timeout_seconds=1)
        with patch("jireh.financial_aid.clamav_instream.socket.create_connection", return_value=fake), patch("time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(ClamdScanError, "scanner_unavailable"):
                scanner.scan(b"fictional")


if __name__ == '__main__':
    unittest.main()
