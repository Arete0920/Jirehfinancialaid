"""Synthetic-only document metadata guard tests: no files or uploads."""
import unittest
from dataclasses import FrozenInstanceError
from uuid import uuid4

from jireh.financial_aid.document_preflight import (
    CandidateDocumentPolicy,
    DocumentPreflightError,
    validate_document_candidate,
)


SCHOOL_A = str(uuid4())
SCHOOL_B = str(uuid4())
YEAR_A = str(uuid4())
YEAR_B = str(uuid4())
HOUSEHOLD_A = str(uuid4())
APPLICATION_A = str(uuid4())
FICTIONAL_DIGEST = "a" * 64


def policy(**overrides):
    values = dict(
        policy_version="synthetic-document-policy-v1",
        school_id=SCHOOL_A,
        academic_year_id=YEAR_A,
        allowed_declared_media_types=("application/pdf", "image/png"),
        maximum_bytes=1_000_000,
    )
    values.update(overrides)
    return CandidateDocumentPolicy(**values)


def candidate(**overrides):
    values = dict(
        policy=policy(),
        school_id=SCHOOL_A,
        academic_year_id=YEAR_A,
        household_id=HOUSEHOLD_A,
        application_id=APPLICATION_A,
        claimed_media_type="application/pdf",
        claimed_byte_count=1024,
        claimed_sha256=FICTIONAL_DIGEST,
    )
    values.update(overrides)
    return validate_document_candidate(**values)


class DocumentPreflightTests(unittest.TestCase):
    def assert_rejected(self, code, **kwargs):
        with self.assertRaises(DocumentPreflightError) as result:
            candidate(**kwargs)
        self.assertEqual(str(result.exception), code)

    def test_bounded_candidate_never_grants_upload_or_storage(self):
        result = candidate()
        self.assertEqual(result.claimed_byte_count, 1024)
        self.assertEqual(result.claimed_sha256, FICTIONAL_DIGEST)
        self.assertEqual(result.policy_version, "synthetic-document-policy-v1")
        self.assertEqual(str(result.school_id), SCHOOL_A)
        self.assertEqual(str(result.household_id), HOUSEHOLD_A)
        self.assertTrue(result.requires_trusted_access_check)
        self.assertTrue(result.requires_server_side_type_detection)
        self.assertTrue(result.requires_malware_scan)
        self.assertTrue(result.requires_approved_encrypted_storage)
        self.assertFalse(result.storage_permitted)
        self.assertFalse(hasattr(result, "storage_url"))
        self.assertFalse(hasattr(result, "upload_token"))
        self.assertFalse(hasattr(result, "file_bytes"))
        self.assertNotIn(FICTIONAL_DIGEST, repr(result))
        with self.assertRaises(FrozenInstanceError):
            result.storage_permitted = True

    def test_missing_or_malformed_policy_never_defaults_to_accept(self):
        self.assert_rejected("document_policy_missing", policy=None)
        self.assert_rejected("document_policy_missing", policy={})
        for version in ("", None, "unsafe policy", True, "x" * 65):
            with self.subTest(version=version):
                self.assert_rejected(
                    "document_policy_version_invalid",
                    policy=policy(policy_version=version),
                )

    def test_cross_school_year_and_invalid_identity_fail_closed(self):
        self.assert_rejected("document_policy_scope_mismatch", school_id=SCHOOL_B)
        self.assert_rejected("document_policy_scope_mismatch", academic_year_id=YEAR_B)
        self.assert_rejected(
            "document_policy_school_invalid", policy=policy(school_id="invalid")
        )
        self.assert_rejected(
            "document_policy_year_invalid", policy=policy(academic_year_id=None)
        )
        for name, code in (
            ("school_id", "document_school_invalid"),
            ("academic_year_id", "document_year_invalid"),
            ("household_id", "document_household_invalid"),
            ("application_id", "document_application_invalid"),
        ):
            for value in (None, "not-a-uuid", True, 17, {}, []):
                with self.subTest(name=name, value=value):
                    self.assert_rejected(code, **{name: value})
        self.assert_rejected(
            "document_application_invalid",
            application_id=APPLICATION_A.upper(),
        )

    def test_explicit_media_policy_only(self):
        for options in (
            None, (), [], ("application/pdf", "application/pdf"),
            ("APPLICATION/PDF",), ("",), ("application/pdf;evil",),
            ("application/pdf", None), ("application/pdf", "not-a-type"),
        ):
            with self.subTest(options=options):
                self.assert_rejected(
                    "document_media_policy_missing",
                    policy=policy(allowed_declared_media_types=options),
                )
        for value in (
            "application/x-msdownload", "application/zip", "text/html",
            "application/pdf; charset=utf-8", "APPLICATION/PDF", "", None,
            True, b"application/pdf",
        ):
            with self.subTest(value=value):
                self.assert_rejected(
                    "document_claimed_media_type_not_allowed",
                    claimed_media_type=value,
                )

    def test_size_is_integer_nonzero_and_bounded_by_explicit_policy(self):
        for value in (0, -1, None, True, False, 2.5, "1024", [], {}):
            with self.subTest(value=value):
                self.assert_rejected(
                    "document_claimed_size_invalid",
                    claimed_byte_count=value,
                )
        for limit in (None, 0, True, -1, 2.1, 2**64):
            with self.subTest(limit=limit):
                self.assert_rejected(
                    "document_size_policy_missing",
                    policy=policy(maximum_bytes=limit),
                )
        self.assert_rejected(
            "document_claimed_size_exceeds_policy",
            claimed_byte_count=1_000_001,
        )
        self.assertEqual(
            candidate(claimed_byte_count=1_000_000).claimed_byte_count,
            1_000_000,
        )

    def test_digest_is_exact_lowercase_sha256_format_not_integrity_proof(self):
        for digest in (
            None, "", True, "a" * 63, "a" * 65,
            "A" * 64, "g" * 64, "sha256:" + "a" * 64,
            b"a" * 64, {}, [],
        ):
            with self.subTest(type=type(digest), length=len(digest) if isinstance(digest, str) else 0):
                self.assert_rejected(
                    "document_claimed_digest_invalid", claimed_sha256=digest
                )

    def test_untrusted_claims_never_derive_grants_or_scan_results(self):
        # Matching UUIDs are NOT an access check: no identities, grants,
        # malware tests, storage or backends are contacted by this module.
        result = candidate(claimed_media_type="image/png")
        self.assertFalse(result.storage_permitted)
        self.assertTrue(result.requires_trusted_access_check)
        self.assertTrue(result.requires_malware_scan)

    def test_error_messages_are_constant_and_do_not_echo_private_inputs(self):
        secret = "FICTIONAL_PRIVATE_TAX_DATA_9988"
        with self.assertRaises(DocumentPreflightError) as error:
            candidate(claimed_media_type=secret)
        self.assertEqual(
            str(error.exception), "document_claimed_media_type_not_allowed"
        )
        self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()
