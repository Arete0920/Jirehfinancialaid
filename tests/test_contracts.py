"""Regression tests for the initial standalone product contracts."""

import unittest

from jireh.financial_aid.buckets import AidBucket
from jireh.financial_aid.fees import (
    APPLICATION_FEE_PAYER,
    APPLICATION_FEE_SCOPE,
    HOUSEHOLD_APPLICATION_FEE_CENTS,
)


class FinancialAidContractTests(unittest.TestCase):
    def test_all_five_buckets_have_stable_source_codes(self):
        self.assertEqual(
            [(bucket.name, bucket.value) for bucket in AidBucket],
            [
                ("NEED", "need"),
                ("MISSION", "mission"),
                ("MARKETING", "marketing"),
                ("MERIT", "merit"),
                ("HARDSHIP", "hardship"),
            ],
        )

    def test_bucket_values_are_unique_and_parseable(self):
        self.assertEqual(len(set(bucket.value for bucket in AidBucket)), 5)
        for bucket in AidBucket:
            with self.subTest(bucket=bucket):
                self.assertIs(AidBucket(bucket.value), bucket)

    def test_household_application_fee_is_55_dollars(self):
        self.assertEqual(HOUSEHOLD_APPLICATION_FEE_CENTS, 5_500)
        self.assertEqual(APPLICATION_FEE_PAYER, "family")
        self.assertEqual(APPLICATION_FEE_SCOPE, "household")


if __name__ == "__main__":
    unittest.main()
