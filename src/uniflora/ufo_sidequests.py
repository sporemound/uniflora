from __future__ import annotations

import re
from urllib.parse import urlencode, urlunsplit

_UFOSINT_SOURCE_KEY = "ufosint"
_UFOSINT_REPORT_ID = re.compile(r"^[1-9][0-9]{0,18}$")
_DISCORD_APPLICATION_ID = re.compile(r"^[1-9][0-9]{16,19}$")


def canonical_ufosint_report_id(
    source_key: str,
    report_id: str,
) -> str | None:
    """Return the numeric provider ID without a duplicated source prefix."""

    if source_key.strip().casefold() != _UFOSINT_SOURCE_KEY:
        return None
    normalized = report_id.strip()
    prefix = f"{_UFOSINT_SOURCE_KEY}:"
    if normalized.casefold().startswith(prefix):
        normalized = normalized[len(prefix) :]
    return normalized if _UFOSINT_REPORT_ID.fullmatch(normalized) else None


def build_ufosint_sidequest_url(
    discord_application_id: int | str | None,
    *,
    source_key: str,
    report_id: str,
) -> str | None:
    """Build an official Discord Activity deep link for one UFOSINT record."""

    canonical_id = canonical_ufosint_report_id(source_key, report_id)
    if isinstance(discord_application_id, bool) or discord_application_id is None:
        return None
    application_id = str(discord_application_id).strip()
    if canonical_id is None or not _DISCORD_APPLICATION_ID.fullmatch(application_id):
        return None

    query = urlencode({"custom_id": f"{_UFOSINT_SOURCE_KEY}:{canonical_id}"})
    return urlunsplit(
        ("https", "discord.com", f"/activities/{application_id}", query, "")
    )
