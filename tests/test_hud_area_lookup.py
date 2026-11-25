"""Acceptance for resolving trusted fictional location evidence to HUD rent areas."""

from dataclasses import replace
from unittest import TestCase

from jireh.financial_aid.assessment_contract import CandidateAssessmentError
from jireh.financial_aid.hud_area_lookup import (
    FictionalHudAddressGeography,
    FictionalHudAreaCrosswalk,
    FictionalHudAreaRow,
    resolve_fictional_hud_area,
)


class FictionalHudAreaLookupTests(TestCase):
    def setUp(self):
        self.crosswalk = FictionalHudAreaCrosswalk(2027, (
            FictionalHudAreaRow("0900101234", "fictional-unified-area"),
            FictionalHudAreaRow("0900105678", "fictional-unified-area"),
            FictionalHudAreaRow("0900301234", "fictional-north-area"),
            FictionalHudAreaRow("0900305678", "fictional-south-area"),
        ))
        self.location = FictionalHudAddressGeography(county_fips="09001", address_verified=True)

    def resolve(self, **overrides):
        return resolve_fictional_hud_area(**({
            "geography": self.location,
            "crosswalk": self.crosswalk,
            "expected_hud_fiscal_year": 2027,
            "expected_crosswalk_sha256": "23cce5c8257466bfcf4118efbe4efb6b8ce9998fb89ee7111a5fd590e654e51f",
        } | overrides))

    def test_verified_county_resolves_only_when_all_hud_entries_agree(self):
        self.assertEqual(self.resolve(), "fictional-unified-area")
        reordered = replace(self.crosswalk, rows=tuple(reversed(self.crosswalk.rows)))
        self.assertEqual(self.resolve(crosswalk=reordered), "fictional-unified-area")
        with self.assertRaisesRegex(CandidateAssessmentError, "^hud_area_geography_ambiguous$"):
            self.resolve(geography=replace(self.location, county_fips="09003"))

    def test_verified_exact_hud_key_resolves_a_split_county(self):
        for key, area in (("0900301234", "fictional-north-area"),
                          ("0900305678", "fictional-south-area")):
            geography = FictionalHudAddressGeography("09003", True, key)
            with self.subTest(key=key):
                self.assertEqual(self.resolve(geography=geography), area)

    def test_missing_unverified_unknown_and_mismatched_geography_fail_closed(self):
        for geography, code in (
            (replace(self.location, address_verified=False), "hud_area_location_unverified"),
            (replace(self.location, address_verified=1), "hud_area_location_unverified"),
            (replace(self.location, county_fips=None), "hud_area_county_invalid"),
            (replace(self.location, county_fips=9001), "hud_area_county_invalid"),
            (replace(self.location, county_fips="０９００１"), "hud_area_county_invalid"),
            (replace(self.location, county_fips="09005"), "hud_area_geography_unavailable"),
            (replace(self.location, hud_geography_code="0900301234"), "hud_area_geography_scope_mismatch"),
            (replace(self.location, hud_geography_code="0900199999"), "hud_area_geography_unavailable"),
            (replace(self.location, hud_geography_code="09001"), "hud_area_geography_invalid"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(CandidateAssessmentError, f"^{code}$"):
                self.resolve(geography=geography)

    def test_crosswalk_year_and_exact_contents_are_required(self):
        with self.assertRaisesRegex(CandidateAssessmentError, "^hud_area_crosswalk_year_mismatch$"):
            self.resolve(expected_hud_fiscal_year=2026)
        first, *rest = self.crosswalk.rows
        changed = replace(first, area_code="fictional-newly-supplied-area")
        with self.assertRaisesRegex(CandidateAssessmentError, "^hud_area_crosswalk_digest_mismatch$"):
            self.resolve(crosswalk=replace(self.crosswalk, rows=(changed, *rest)))
        with self.assertRaisesRegex(CandidateAssessmentError, "^hud_area_crosswalk_pin_invalid$"):
            self.resolve(expected_crosswalk_sha256="x" * 64)

    def test_duplicate_or_malformed_crosswalk_rows_are_rejected(self):
        first, *rest = self.crosswalk.rows
        for rows, code in (
            ((first, *rest, first), "hud_area_crosswalk_duplicate"),
            ((replace(first, geography_code="09001"), *rest), "hud_area_crosswalk_row_invalid"),
            ((replace(first, area_code=" separate "), *rest), "hud_area_crosswalk_row_invalid"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(CandidateAssessmentError, f"^{code}$"):
                self.resolve(crosswalk=replace(self.crosswalk, rows=rows))
