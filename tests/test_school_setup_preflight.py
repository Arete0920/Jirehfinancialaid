"""Pure school setup preflight remains non-operational and fail-closed."""
import unittest
from dataclasses import FrozenInstanceError

from jireh.schools.school_setup_preflight import (
    SchoolSetupCandidate,
    SchoolSetupPreflightError,
    validate_school_setup_candidate,
)


class SchoolSetupPreflightTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "code": "christian-academy-1",
            "name": "St. Anne's Academy",
            "timezone": "America/New_York",
            "idempotency_key": "123e4567-e89b-42d3-a456-426614174000",
        }

    def test_valid_proposal_is_frozen_and_has_no_activation_flag(self):
        candidate = validate_school_setup_candidate(self.payload)
        self.assertIsInstance(candidate, SchoolSetupCandidate)
        self.assertEqual(candidate.code, self.payload["code"])
        self.assertEqual(candidate.name, self.payload["name"])
        self.assertEqual(candidate.timezone, self.payload["timezone"])
        self.assertFalse(hasattr(candidate, "is_active"))
        self.assertFalse(hasattr(candidate, "payment_provider"))
        with self.assertRaises(FrozenInstanceError):
            candidate.code = "changed"

    def test_rejects_non_objects_missing_and_extra_fields(self):
        for data in (None, [], "", (), {}, {"code": "school"}, 7):
            with self.subTest(data=data), self.assertRaises(SchoolSetupPreflightError):
                validate_school_setup_candidate(data)
        for key in ("payment_provider", "sis", "integration", "plan_code",
                    "is_active", "operator", "domain", "tenant_id", "credentials"):
            with self.subTest(extra=key), self.assertRaises(SchoolSetupPreflightError):
                validate_school_setup_candidate({**self.payload, key: "unsafe"})

    def test_does_not_coerce_nonstring_or_nested_values(self):
        for field in self.payload:
            for value in (None, True, 100, ["x"], {"key": "x"}):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(SchoolSetupPreflightError):
                        validate_school_setup_candidate({**self.payload, field: value})

    def test_school_code_matches_jireh_model_length_and_safe_slug(self):
        valid = ("school", "x", "s-2", "a" * 64)
        invalid = ("", "A-School", "-school", "school-", "two--dashes",
                   "school_1", "school/name", " school", "a" * 65,
                   "school\n", "schοol")
        for value in valid:
            with self.subTest(valid=value):
                self.assertEqual(
                    validate_school_setup_candidate({**self.payload, "code": value}).code,
                    value,
                )
        for value in invalid:
            with self.subTest(invalid=value):
                with self.assertRaises(SchoolSetupPreflightError):
                    validate_school_setup_candidate({**self.payload, "code": value})

    def test_school_name_rejects_control_bidi_and_whitespace_confusion(self):
        for value in ("", "  ", " Leading", "Trailing ", "Line\nBreak",
                      "Invisible\u200bName", "Bidi\u202eName", "X" * 256):
            with self.subTest(value=value), self.assertRaises(SchoolSetupPreflightError):
                validate_school_setup_candidate({**self.payload, "name": value})
        for value in ("St. Anne's Academy", "École Sainte-Marie", "N. School (K-12)"):
            with self.subTest(value=value):
                self.assertEqual(
                    validate_school_setup_candidate({**self.payload, "name": value}).name,
                    value,
                )

    def test_timezone_requires_constrained_shape_not_url_or_header(self):
        for value in ("UTC", "America/New_York", "Etc/GMT+1"):
            with self.subTest(valid=value):
                self.assertEqual(
                    validate_school_setup_candidate({**self.payload, "timezone": value}).timezone,
                    value,
                )
        for value in ("", "/etc/passwd", "../UTC", "America//New_York",
                      "America/New York", "UTC;DROP", "https://example.com",
                      "America/New_York\nInjected", "A" * 65):
            with self.subTest(invalid=value):
                with self.assertRaises(SchoolSetupPreflightError):
                    validate_school_setup_candidate({**self.payload, "timezone": value})

    def test_idempotency_key_is_canonical_nonzero_uuid(self):
        key = self.payload["idempotency_key"]
        for value in ("", "not-a-uuid", "0" * 32,
                      "00000000-0000-0000-0000-000000000000",
                      key.upper(), "{" + key + "}", " " + key, key.replace("-", "")):
            with self.subTest(key=value):
                with self.assertRaises(SchoolSetupPreflightError):
                    validate_school_setup_candidate({**self.payload, "idempotency_key": value})
        self.assertEqual(
            validate_school_setup_candidate(self.payload).idempotency_key, key,
        )


if __name__ == "__main__":
    unittest.main()
