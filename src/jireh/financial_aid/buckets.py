"""Approved school financial-aid bucket identifiers.

These codes preserve the five categories in the existing financial-aid source.
No award calculation, allocation, or approval is performed by this module.
"""

from enum import StrEnum


class AidBucket(StrEnum):
    NEED = "need"
    MISSION = "mission"
    MARKETING = "marketing"
    MERIT = "merit"
    HARDSHIP = "hardship"
