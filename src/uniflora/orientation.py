from __future__ import annotations

import re
from enum import StrEnum


class OrientationIntent(StrEnum):
    NONE = "none"
    LOCAL = "local"
    EXPLICIT_SUMMARY = "explicit_summary"
    TARGETED_INQUIRY = "targeted_inquiry"


_EXPLICIT_SUMMARY_PHRASES = (
    "recap",
    "orientation summary",
    "accessibility summary",
    "map overview",
    "confirmed public state",
    "full map",
    "full orientation",
)

_TARGETED_TERMS = frozenset(
    {
        "need",
        "capacity",
        "structure",
        "history",
        "risk",
        "reservoir",
        "growth",
        "path",
        "pathway",
        "route",
        "water",
        "salinity",
        "evaporation",
        "measurement",
        "reserve",
        "viability",
        "north",
        "east",
        "south",
        "west",
        "damaged",
    }
)

_GENERIC_PATTERNS = (
    re.compile(r"\b(?:get|gets|getting|find|finds) (?:their |her |his )?bearings\b"),
    re.compile(r"\blooks? around\b"),
    re.compile(r"\bsurveys? (?:the )?(?:area|surroundings)\b"),
    re.compile(r"\btr(?:y|ies) to understand where (?:they|she|he) (?:are|is)\b"),
    re.compile(r"\btakes? in (?:the )?surroundings\b"),
)


def classify_orientation(
    message: str, *, additional_targeted_terms: frozenset[str] = frozenset()
) -> OrientationIntent:
    """Classify reveal scope; this function never interprets puzzle facts."""

    normalized = " ".join(message.casefold().split())
    if any(phrase in normalized for phrase in _EXPLICIT_SUMMARY_PHRASES):
        return OrientationIntent.EXPLICIT_SUMMARY
    generic = any(pattern.search(normalized) for pattern in _GENERIC_PATTERNS)
    if not generic:
        return OrientationIntent.NONE
    words = set(re.findall(r"[a-z]+", normalized))
    if words & (_TARGETED_TERMS | additional_targeted_terms):
        return OrientationIntent.TARGETED_INQUIRY
    return OrientationIntent.LOCAL
