"""Resolve preverified fictional geography against an exact HUD area crosswalk."""

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .assessment_contract import _reject
from .regional_need import _SHA256, _valid_identifier


_COUNTY_FIPS = re.compile(r"[0-9]{5}")
_HUD_GEOGRAPHY_CODE = re.compile(r"[0-9]{10}")


@dataclass(frozen=True, slots=True, repr=False)
class FictionalHudAddressGeography:
    """Identifiers established by a trusted address verifier for the HUD release.

    A verifier must establish both the county and any exact HUD geography
    code it supplies. User-entered codes do not establish residence evidence.
    """

    county_fips: str
    address_verified: bool
    hud_geography_code: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class FictionalHudAreaRow:
    geography_code: str
    area_code: str


@dataclass(frozen=True, slots=True, repr=False)
class FictionalHudAreaCrosswalk:
    hud_fiscal_year: int
    rows: tuple[FictionalHudAreaRow, ...]


def _pinned_area_index(crosswalk, expected_year, expected_digest):
    if (type(expected_year) is not int or not 1 <= expected_year <= 9999
            or type(expected_digest) is not str or _SHA256.fullmatch(expected_digest) is None):
        _reject("hud_area_crosswalk_pin_invalid")
    if (type(crosswalk) is not FictionalHudAreaCrosswalk
            or type(crosswalk.hud_fiscal_year) is not int
            or type(crosswalk.rows) is not tuple or not crosswalk.rows):
        _reject("hud_area_crosswalk_invalid")
    if crosswalk.hud_fiscal_year != expected_year:
        _reject("hud_area_crosswalk_year_mismatch")

    areas_by_geography = {}
    for row in crosswalk.rows:
        if (type(row) is not FictionalHudAreaRow
                or type(row.geography_code) is not str
                or _HUD_GEOGRAPHY_CODE.fullmatch(row.geography_code) is None
                or not _valid_identifier(row.area_code)):
            _reject("hud_area_crosswalk_row_invalid")
        if row.geography_code in areas_by_geography:
            _reject("hud_area_crosswalk_duplicate")
        areas_by_geography[row.geography_code] = row.area_code

    # Match the fiscal year and sorted geography/area pairs, independent of row order.
    payload = json.dumps([expected_year, sorted(areas_by_geography.items())], separators=(",", ":"))
    if sha256(payload.encode("ascii")).hexdigest() != expected_digest:
        _reject("hud_area_crosswalk_digest_mismatch")
    return areas_by_geography


def resolve_fictional_hud_area(
    *,
    geography: FictionalHudAddressGeography,
    crosswalk: FictionalHudAreaCrosswalk,
    expected_hud_fiscal_year: int,
    expected_crosswalk_sha256: str,
) -> str:
    """Return one rent area for the household's verified geography.

    County-only evidence is sufficient if every published entry for that
    county maps to the same area. For a split county the caller must supply
    a verified exact HUD geography code from the pinned release.
    """
    if type(geography) is not FictionalHudAddressGeography or geography.address_verified is not True:
        _reject("hud_area_location_unverified")
    county = geography.county_fips
    if type(county) is not str or _COUNTY_FIPS.fullmatch(county) is None:
        _reject("hud_area_county_invalid")

    key = geography.hud_geography_code
    if key is not None:
        if type(key) is not str or _HUD_GEOGRAPHY_CODE.fullmatch(key) is None:
            _reject("hud_area_geography_invalid")
        if not key.startswith(county):
            _reject("hud_area_geography_scope_mismatch")

    areas_by_geography = _pinned_area_index(
        crosswalk, expected_hud_fiscal_year, expected_crosswalk_sha256,
    )
    if key is not None:
        area = areas_by_geography.get(key)
        if area is None:
            _reject("hud_area_geography_unavailable")
        return area

    areas = {area for code, area in areas_by_geography.items() if code.startswith(county)}
    if not areas:
        _reject("hud_area_geography_unavailable")
    if len(areas) > 1:
        _reject("hud_area_geography_ambiguous")
    return next(iter(areas))
