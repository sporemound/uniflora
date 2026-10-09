from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_MAX_FEED_BYTES = 2_000_000
_MAX_REPORTS = 500
_MAX_SEEN_IDS = 5_000
_UFOSINT_MCP_URL = "https://ufosint.com/mcp"
_ACTIVITY_UFO_REPORTS_URL = os.environ.get("UNIFLORA_ACTIVITY_UFO_REPORTS_URL", "")
_UFOSINT_PAGE_URL = "https://ufosint.com/"
_ALLOWED_SOURCE_MODES = {"ufosint", "approved-json"}
_ALLOWED_AUTHORIZATION_MODES = {
    "api",
    "first-party",
    "licensed",
    "written-permission",
}
_ALLOWED_PRECISIONS = {"city", "region", "approximate", "unknown"}
_ALLOWED_STATUSES = {"unverified", "explained", "investigated", "unknown"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$")


class UfoReportFeedError(RuntimeError):
    """Raised when an external report source is unavailable or invalid."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise UfoReportFeedError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise UfoReportFeedError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _bounded_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())[:maximum]


def _bounded_list_text(value: object, maximum: int) -> str:
    if isinstance(value, str):
        return _bounded_text(value, maximum)
    if not isinstance(value, (list, tuple)):
        return ""
    parts = [_bounded_text(item, 50) for item in value]
    return ", ".join(item for item in parts if item)[:maximum]


def _parse_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise UfoReportFeedError(f"{field} must be an ISO-8601 timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UfoReportFeedError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise UfoReportFeedError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _parse_ufosint_event_date(value: object) -> datetime | None:
    """Accept only a day-specific UFOSINT event date.

    Year-only and month-only records are deliberately excluded. They are too
    imprecise for a current-report map and must never be announced as recent.
    """

    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|[T ])", value.strip())
    if match is None:
        return None
    try:
        parsed = date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return datetime.combine(parsed, time.min, tzinfo=UTC)


def _normalized_host(hostname: str | None) -> str:
    return (hostname or "").strip().casefold().rstrip(".").removeprefix("www.")


def _safe_public_https_url(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UfoReportFeedError(f"{field} must be a non-empty HTTPS URL")
    parsed = urlparse(value.strip())
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise UfoReportFeedError(f"{field} must use HTTPS")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        raise UfoReportFeedError(f"{field} must not target a local host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UfoReportFeedError(f"{field} must not target a private address")
    return parsed.geturl()


def _optional_source_url(value: object, *, source_page_url: str) -> str | None:
    if value in (None, ""):
        return None
    candidate = _safe_public_https_url(value, field="sourceUrl")
    if _normalized_host(urlparse(candidate).hostname) != _normalized_host(
        urlparse(source_page_url).hostname
    ):
        raise UfoReportFeedError(
            "sourceUrl must use the same public host as source.pageUrl"
        )
    return candidate


def _quantize_coordinate(value: float) -> float:
    # Roughly city-level precision. Do not imply a residence or witness point.
    return round(round(value / 0.05) * 0.05, 4)


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unwrap_tool_result(value: object) -> dict[str, Any] | None:
    """Accept the direct REST object and conservative wrapper variants."""

    if not isinstance(value, dict):
        return None
    for key in ("result", "data"):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value


_REMOVED_REPORT_PHRASES = (
    "no description available",
    "post was deleted",
    "post was removed",
    "removed by moderators",
    "original post was removed",
    "original post was deleted",
    "post body was removed",
    "post body was deleted",
    "op comments were removed",
    "contains no description",
    "no information is available",
)


def _removed_or_empty_description(value: object) -> bool:
    description = _bounded_text(value, 2_000).casefold()

    if not description:
        return True

    return any(
        phrase in description
        for phrase in _REMOVED_REPORT_PHRASES
    )


def _local_ufosint_quality(
    record: dict[str, Any],
    *,
    observed_at: datetime,
    retrieved_at: datetime,
) -> int:
    score = 0

    if observed_at <= retrieved_at:
        score += 15

    latitude = _number(record.get("latitude"))
    longitude = _number(record.get("longitude"))

    if (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        score += 25

    if (
        _bounded_text(record.get("city"), 100)
        and _bounded_text(record.get("country"), 100)
    ):
        score += 15

    description = _bounded_text(
        record.get("description"),
        2_000,
    )

    if (
        len(description) >= 40
        and not _removed_or_empty_description(description)
    ):
        score += 20

    if _bounded_text(
        record.get("standardized_shape")
        or record.get("shape"),
        64,
    ):
        score += 10

    if _bounded_text(record.get("duration"), 100):
        score += 5

    witnesses = _integer(record.get("num_witnesses"))

    if witnesses is not None and witnesses > 0:
        score += 5

    if _bounded_text(
        record.get("source_name")
        or record.get("source"),
        80,
    ):
        score += 5

    return min(100, score)


def _unwrap_mcp_tool_payload(value: object) -> object:
    if not isinstance(value, dict):
        raise UfoReportFeedError(
            "UFOSINT returned an invalid MCP response"
        )

    result = value.get("result")

    if not isinstance(result, dict):
        raise UfoReportFeedError(
            "UFOSINT returned no MCP result"
        )

    content = result.get("content")

    if not isinstance(content, list):
        raise UfoReportFeedError(
            "UFOSINT returned no MCP content"
        )

    text_payload = next(
        (
            item.get("text")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ),
        None,
    )

    if text_payload is None:
        raise UfoReportFeedError(
            "UFOSINT returned no tool text payload"
        )

    try:
        parsed = json.loads(text_payload)
    except json.JSONDecodeError as exc:
        raise UfoReportFeedError(
            "UFOSINT returned invalid tool JSON"
        ) from exc

    if result.get("isError") is True:
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("error"), str)
        ):
            raise UfoReportFeedError(parsed["error"])

        raise UfoReportFeedError(
            "UFOSINT tool request failed"
        )

    return parsed


def _ufosint_location(record: dict[str, Any]) -> str:
    values = [
        _bounded_text(record.get("city"), 100),
        _bounded_text(record.get("state"), 100),
        _bounded_text(record.get("country"), 100),
    ]
    return ", ".join(value for value in values if value) or "Approximate location"


def _sanitize_witness_summary(value: object, maximum: int = 2_000) -> str:
    raw = _bounded_text(value, 8_000)
    if _removed_or_empty_description(raw):
        return ""

    raw = re.sub(r"https?://\S+", "[link removed]", raw, flags=re.IGNORECASE)
    raw = re.sub(
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        "[contact removed]",
        raw,
    )
    raw = re.sub(
        r"(^|\s)@[A-Za-z0-9_]{2,32}\b",
        r"\1[username removed]",
        raw,
    )
    raw = re.sub(
        r"\b(?:\+?\d[\d(). -]{7,}\d)\b",
        "[contact removed]",
        raw,
    )
    return re.sub(r"\s+", " ", raw).strip()[:maximum]


def _ufosint_summary(record: dict[str, Any]) -> str:
    """Return a bounded witness summary, with metadata as a fallback."""

    witness_summary = _sanitize_witness_summary(record.get("description"), 2_000)
    if witness_summary:
        return witness_summary

    details: list[str] = []
    shape = _bounded_text(
        record.get("standardized_shape") or record.get("shape"), 64
    )
    if shape:
        details.append(f"reported form: {shape}")
    duration = _bounded_text(record.get("duration"), 100)
    if duration:
        details.append(f"duration: {duration}")
    witnesses = _integer(record.get("num_witnesses"))
    if witnesses is not None and witnesses > 0:
        details.append(f"witness count: {witnesses}")
    source = _bounded_text(record.get("source_name") or record.get("source"), 80)
    prefix = "UFOSINT indexed a quality-screened sighting"
    if source:
        prefix += f" derived from {source}"
    return f"{prefix}; {'; '.join(details)}." if details else f"{prefix}."



@dataclass(frozen=True, slots=True)
class ExternalUfoReport:
    report_id: str
    source_key: str
    source_name: str
    source_page_url: str
    source_url: str | None
    authorization_mode: str
    observed_at: datetime
    indexed_at: datetime
    latitude: float
    longitude: float
    title: str
    location_name: str
    coordinate_precision: str
    summary: str
    status: str
    quality_score: int

    @property
    def marker(self) -> str:
        digest = hashlib.sha256(
            f"{self.source_key}:{self.report_id}".encode()
        ).hexdigest()[:20]
        return f"Hypha external report · {digest}"

    def is_recent_event(self, now: datetime, maximum_age_hours: int) -> bool:
        minimum = now - timedelta(hours=maximum_age_hours)
        maximum = now + timedelta(minutes=15)
        return minimum <= self.observed_at <= maximum


def _report_recency_key(report: ExternalUfoReport) -> tuple[datetime, datetime, int, str]:
    """Order reports by app/source discovery recency, not sighting date alone."""

    numeric_id = _integer(report.report_id.removeprefix("ufosint:"))
    return (
        report.indexed_at,
        report.observed_at,
        numeric_id or 0,
        report.report_id,
    )


@dataclass(frozen=True, slots=True)
class UfoReportFeed:
    source_key: str
    source_name: str
    source_page_url: str
    license_text: str
    authorization_mode: str
    retrieved_at: datetime
    reports: tuple[ExternalUfoReport, ...]


@dataclass(frozen=True, slots=True)
class UfoReportSettings:
    enabled: bool
    source_mode: str
    feed_url: str | None
    channel_id: int | None
    poll_seconds: int
    event_max_age_hours: int
    max_announcements_per_poll: int
    state_path: Path
    voice_enabled: bool
    minimum_quality_score: int
    ufosint_lookback_days: int
    ufosint_candidate_limit: int

    @classmethod
    def from_environment(
        cls,
        *,
        default_channel_id: int | None,
    ) -> UfoReportSettings:
        enabled = _env_bool("UFO_REPORTS_ENABLED")
        source_mode = os.getenv("UFO_REPORTS_SOURCE", "ufosint").strip().casefold()
        if source_mode not in _ALLOWED_SOURCE_MODES:
            raise UfoReportFeedError(
                "UFO_REPORTS_SOURCE must be ufosint or approved-json"
            )
        feed_raw = os.getenv("UFO_REPORTS_FEED_URL", "").strip()
        feed_url = (
            _safe_public_https_url(feed_raw, field="UFO_REPORTS_FEED_URL")
            if feed_raw
            else None
        )
        channel_raw = os.getenv("UFO_REPORTS_CHANNEL_ID", "").strip()
        channel_id = default_channel_id
        if channel_raw:
            try:
                channel_id = int(channel_raw)
            except ValueError as exc:
                raise UfoReportFeedError(
                    "UFO_REPORTS_CHANNEL_ID must be a Discord channel ID"
                ) from exc
            if channel_id <= 0:
                raise UfoReportFeedError(
                    "UFO_REPORTS_CHANNEL_ID must be a positive Discord channel ID"
                )
        if enabled and source_mode == "approved-json" and feed_url is None:
            raise UfoReportFeedError(
                "approved-json mode requires UFO_REPORTS_FEED_URL"
            )
        if enabled and channel_id is None:
            raise UfoReportFeedError(
                "UFO_REPORTS_ENABLED requires UFO_REPORTS_CHANNEL_ID or "
                "V2_BULLETIN_CHANNEL_ID"
            )
        return cls(
            enabled=enabled,
            source_mode=source_mode,
            feed_url=feed_url,
            channel_id=channel_id,
            # UFOSINT explicitly discourages aggressive looped API access.
            poll_seconds=_env_int(
                "UFO_REPORTS_POLL_SECONDS",
                21_600 if source_mode == "ufosint" else 900,
                300,
                86_400,
            ),
            event_max_age_hours=_env_int(
                "UFO_REPORTS_EVENT_MAX_AGE_HOURS", 48, 1, 168
            ),
            max_announcements_per_poll=_env_int(
                "UFO_REPORTS_MAX_ANNOUNCEMENTS_PER_POLL", 3, 1, 10
            ),
            state_path=Path(
                os.getenv(
                    "UFO_REPORTS_STATE_PATH",
                    "./data/ufo-report-intake-state.json",
                )
            ),
            voice_enabled=_env_bool("UFO_REPORTS_VOICE_ENABLED", True),
            # "Above 50%" means the minimum accepted integer score is 51.
            minimum_quality_score=_env_int(
                "UFO_REPORTS_MIN_QUALITY_SCORE", 51, 51, 100
            ),
            ufosint_lookback_days=_env_int(
                "UFOSINT_LOOKBACK_DAYS", 365, 7, 3_650
            ),
            # Each calendar-month query is capped at 200 records.
            ufosint_candidate_limit=_env_int(
                "UFOSINT_CANDIDATE_LIMIT", 200, 1, 200
            ),
        )


@dataclass(frozen=True, slots=True)
class UfoReportPoll:
    feed: UfoReportFeed
    first_successful_poll: bool
    unseen_reports: tuple[ExternalUfoReport, ...]


def parse_ufo_report_feed(
    value: object,
    *,
    now: datetime | None = None,
    minimum_quality_score: int = 51,
) -> UfoReportFeed:
    """Parse a normalized partner feed with the same strict quality gate."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not isinstance(value, dict) or value.get("schemaVersion") not in {
        "1.0.0",
        "1.1.0",
    }:
        raise UfoReportFeedError(
            "approved UFO feed must use schemaVersion 1.0.0 or 1.1.0"
        )
    source = value.get("source")
    authorization = value.get("authorization")
    reports_value = value.get("reports")
    if not isinstance(source, dict) or not isinstance(authorization, dict):
        raise UfoReportFeedError(
            "approved UFO feed requires source and authorization objects"
        )
    if not isinstance(reports_value, list) or len(reports_value) > _MAX_REPORTS:
        raise UfoReportFeedError(
            f"approved UFO feed must contain no more than {_MAX_REPORTS} reports"
        )

    source_key = _bounded_text(source.get("key"), 64)
    source_name = _bounded_text(source.get("name"), 180)
    source_page_url = _safe_public_https_url(
        source.get("pageUrl"), field="source.pageUrl"
    )
    license_text = _bounded_text(source.get("license"), 180)
    authorization_mode = _bounded_text(authorization.get("mode"), 32)
    authorization_reference = _bounded_text(
        authorization.get("reference"), 500
    )
    if not source_key or not _SAFE_ID.fullmatch(source_key):
        raise UfoReportFeedError("source.key is missing or invalid")
    if not source_name or not license_text:
        raise UfoReportFeedError("source.name and source.license are required")
    if authorization_mode not in _ALLOWED_AUTHORIZATION_MODES:
        raise UfoReportFeedError(
            "authorization.mode must be api, first-party, licensed, or "
            "written-permission"
        )
    if not authorization_reference:
        raise UfoReportFeedError("authorization.reference is required")

    reports: list[ExternalUfoReport] = []
    seen_ids: set[str] = set()
    for candidate in reports_value:
        if not isinstance(candidate, dict):
            raise UfoReportFeedError("each UFO report must be an object")
        quality = _integer(candidate.get("qualityScore"))
        if quality is None or quality < minimum_quality_score:
            continue
        report_id = _bounded_text(candidate.get("id"), 180)
        if not report_id or not _SAFE_ID.fullmatch(report_id):
            raise UfoReportFeedError("report id is missing or invalid")
        compound_id = f"{source_key}:{report_id}"
        if compound_id in seen_ids:
            raise UfoReportFeedError("approved UFO feed contains duplicate ids")
        seen_ids.add(compound_id)

        observed_at = _parse_datetime(candidate.get("observedAt"), "observedAt")
        indexed_at = _parse_datetime(
            candidate.get("indexedAt") or candidate.get("publishedAt"),
            "indexedAt",
        )
        if indexed_at > current + timedelta(minutes=15):
            raise UfoReportFeedError("indexedAt is unreasonably far in the future")
        if observed_at > current + timedelta(hours=24):
            raise UfoReportFeedError("observedAt is unreasonably far in the future")

        latitude = _number(candidate.get("latitude"))
        longitude = _number(candidate.get("longitude"))
        if latitude is None or longitude is None:
            raise UfoReportFeedError(
                "report latitude and longitude must be numeric"
            )
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise UfoReportFeedError("report coordinates are outside Earth bounds")

        coordinate_precision = _bounded_text(
            candidate.get("coordinatePrecision"), 32
        ).casefold()
        status = _bounded_text(candidate.get("status"), 32).casefold()
        if coordinate_precision not in _ALLOWED_PRECISIONS:
            raise UfoReportFeedError(
                "coordinatePrecision must be city, region, approximate, or unknown"
            )
        if status not in _ALLOWED_STATUSES:
            raise UfoReportFeedError(
                "status must be unverified, explained, investigated, or unknown"
            )
        title = _bounded_text(candidate.get("title"), 180)
        location_name = _bounded_text(candidate.get("locationName"), 180)
        summary = _bounded_text(candidate.get("summary"), 350)
        if not title or not location_name:
            raise UfoReportFeedError("report title and locationName are required")

        reports.append(
            ExternalUfoReport(
                report_id=report_id,
                source_key=source_key,
                source_name=source_name,
                source_page_url=source_page_url,
                source_url=_optional_source_url(
                    candidate.get("sourceUrl"), source_page_url=source_page_url
                ),
                authorization_mode=authorization_mode,
                observed_at=observed_at,
                indexed_at=indexed_at,
                latitude=_quantize_coordinate(latitude),
                longitude=_quantize_coordinate(longitude),
                title=title,
                location_name=location_name,
                coordinate_precision=coordinate_precision,
                summary=summary,
                status=status,
                quality_score=quality,
            )
        )

    reports.sort(key=lambda item: (item.observed_at, item.report_id))
    return UfoReportFeed(
        source_key=source_key,
        source_name=source_name,
        source_page_url=source_page_url,
        license_text=license_text,
        authorization_mode=authorization_mode,
        retrieved_at=current,
        reports=tuple(reports),
    )




def parse_ufosint_records(
    search_payload: object,
    detail_payloads: Iterable[object] = (),
    *,
    retrieved_at: datetime,
    minimum_quality_score: int = 51,
) -> UfoReportFeed:
    """Normalize UFOSINT search records and optional detail records.

    Live MCP searches currently provide enough structured fields to work
    without one detail request per record. Tests and compatible callers may
    still supply detail responses; when present, those fields override the
    corresponding search-result fields.
    """

    search = _unwrap_tool_result(search_payload)

    if (
        search is None
        or not isinstance(search.get("results"), list)
    ):
        raise UfoReportFeedError(
            "UFOSINT search response is invalid"
        )

    details_by_id: dict[int, dict[str, Any]] = {}

    for payload in detail_payloads:
        detail = _unwrap_tool_result(payload)

        if detail is None:
            continue

        # Support both a direct sighting record and common wrappers.
        candidate: object = detail

        for key in ("result", "sighting", "record"):
            wrapped = detail.get(key)

            if isinstance(wrapped, dict):
                candidate = wrapped
                break

        if not isinstance(candidate, dict):
            continue

        identifier = _integer(candidate.get("id"))

        if identifier is None or identifier < 1:
            continue

        details_by_id[identifier] = candidate

    reports: list[ExternalUfoReport] = []

    for search_record in search["results"]:
        if not isinstance(search_record, dict):
            continue

        identifier = _integer(search_record.get("id"))

        if identifier is None or identifier < 1:
            continue

        # Detail fields are more complete and intentionally override search
        # fields when supplied.
        record: dict[str, Any] = {
            **search_record,
            **details_by_id.get(identifier, {}),
        }

        observed_at = _parse_ufosint_event_date(
            record.get("date_event")
        )

        # Reject year-only, month-only, invalid, and future event dates.
        if (
            observed_at is None
            or observed_at > retrieved_at
        ):
            continue

        if _removed_or_empty_description(
            record.get("description")
        ):
            continue

        latitude = _number(record.get("latitude"))
        longitude = _number(record.get("longitude"))

        # Map publication requires usable coordinates.
        if latitude is None or longitude is None:
            continue

        if not (
            -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            continue

        # Prefer UFOSINT's explicit quality field when a compatible detail
        # response supplies one. Otherwise calculate the documented local
        # structured-data score used by the live MCP search adapter.
        explicit_quality: int | None = None

        for key in (
            "quality_score",
            "data_quality_score",
            "data_quality",
            "quality",
            "score",
        ):
            value = _integer(record.get(key))

            if value is not None:
                explicit_quality = value
                break

        quality = (
            explicit_quality
            if explicit_quality is not None
            else _local_ufosint_quality(
                record,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
            )
        )

        quality = max(0, min(100, quality))

        # Strict requirement: 50 is rejected and 51 is accepted.
        if quality < minimum_quality_score:
            continue

        location_name = _ufosint_location(record)

        shape = _bounded_text(
            record.get("standardized_shape")
            or record.get("shape"),
            64,
        )

        title = (
            f"{shape} observation near {location_name}"
            if shape
            else f"Unidentified observation near {location_name}"
        )

        reports.append(
            ExternalUfoReport(
                report_id=str(identifier),
                source_key="ufosint",
                source_name="UFOSINT Explorer",
                source_page_url=_UFOSINT_PAGE_URL,
                source_url=None,
                authorization_mode="api",
                observed_at=observed_at,
                indexed_at=retrieved_at,
                latitude=_quantize_coordinate(latitude),
                longitude=_quantize_coordinate(longitude),
                title=title[:180],
                location_name=location_name[:180],
                coordinate_precision="city",
                # _ufosint_summary uses structured derived fields such as
                # source, shape, witness count, duration, and classification.
                # It does not repeat the raw witness narrative.
                summary=_ufosint_summary(record),
                status="unverified",
                quality_score=quality,
            )
        )

    reports.sort(
        key=lambda item: (
            item.observed_at,
            item.report_id,
        )
    )

    return UfoReportFeed(
        source_key="ufosint",
        source_name="UFOSINT Explorer",
        source_page_url=_UFOSINT_PAGE_URL,
        license_text=(
            "UFOSINT public derived fields; "
            "underlying source attribution retained"
        ),
        authorization_mode="api",
        retrieved_at=retrieved_at,
        reports=tuple(reports),
    )

def _read_json_request(
    url: str,
    *,
    body: object | None = None,
    expected_host: str | None = None,
    maximum_response_bytes: int = _MAX_FEED_BYTES,
) -> Any:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Hypha-UFOSINT-Intake/2.0",
        },
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            final_url = _safe_public_https_url(
                response.geturl(), field="external report redirect"
            )
            required_host = expected_host or urlparse(url).hostname or ""
            if _normalized_host(urlparse(final_url).hostname) != _normalized_host(
                required_host
            ):
                raise UfoReportFeedError(
                    "external report request redirected to a different host"
                )
            content_type = response.headers.get_content_type().casefold()
            if content_type not in {
                "application/json",
                "application/geo+json",
                "text/json",
            }:
                raise UfoReportFeedError(
                    "external report source did not return JSON"
                )
            response_body = response.read(
                maximum_response_bytes + 1
            )
    except UfoReportFeedError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UfoReportFeedError("external report request failed") from exc
    if len(response_body) > maximum_response_bytes:
        raise UfoReportFeedError(
            "external report response exceeded "
            f"{maximum_response_bytes} bytes"
        )
    try:
        return json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UfoReportFeedError("external report source returned invalid JSON") from exc




def _monthly_date_slices(start: datetime, end: datetime) -> tuple[tuple[str, str], ...]:
    slices: list[tuple[str, str]] = []
    cursor = datetime(start.year, start.month, 1, tzinfo=UTC)

    while cursor <= end:
        if cursor.month == 12:
            next_month = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
        else:
            next_month = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)

        slice_start = max(start, cursor)
        slice_end = min(end, next_month - timedelta(days=1))
        slices.append((slice_start.date().isoformat(), slice_end.date().isoformat()))
        cursor = next_month

    return tuple(slices)


def _fetch_ufosint_feed(
    settings: UfoReportSettings,
) -> UfoReportFeed:
    now = datetime.now(UTC)
    start = now - timedelta(days=settings.ufosint_lookback_days)
    records_by_id: dict[int, dict[str, Any]] = {}

    for date_from, date_to in _monthly_date_slices(start, now):
        outer = _read_json_request(
            _UFOSINT_MCP_URL,
            body={
                "jsonrpc": "2.0",
                "id": f"hypha-search-{date_from}",
                "method": "tools/call",
                "params": {
                    "name": "search_sightings",
                    "arguments": {
                        "date_from": date_from,
                        "date_to": date_to,
                        "limit": min(settings.ufosint_candidate_limit, 200),
                    },
                },
            },
            expected_host="ufosint.com",
        )

        search = _unwrap_mcp_tool_payload(outer)
        normalized = _unwrap_tool_result(search)
        if normalized is None or not isinstance(normalized.get("results"), list):
            raise UfoReportFeedError(
                f"UFOSINT search response is invalid for {date_from}"
            )

        for record in normalized["results"]:
            if not isinstance(record, dict):
                continue
            identifier = _integer(record.get("id"))
            if identifier is not None and identifier > 0:
                records_by_id[identifier] = record

    combined = {
        "total": len(records_by_id),
        "returned": len(records_by_id),
        "results": list(records_by_id.values()),
    }

    return parse_ufosint_records(
        combined,
        retrieved_at=now,
        minimum_quality_score=settings.minimum_quality_score,
    )

def _fetch_latest_ufosint_report(
    settings: UfoReportSettings,
) -> ExternalUfoReport | None:
    """Return the newest qualifying UFOSINT report from Activity cache.

    The Activity Worker already performs the external UFOSINT import,
    quality screening, deduplication, and caching used by the public map.
    Reusing that endpoint avoids duplicate requests and UFOSINT rate limits.
    """

    now = datetime.now(UTC)

    if not _ACTIVITY_UFO_REPORTS_URL:
        raise UfoReportFeedError("Activity UFO-report endpoint is not configured")
    parsed_url = urlparse(_ACTIVITY_UFO_REPORTS_URL)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise UfoReportFeedError("Activity UFO-report endpoint must use HTTPS")

    payload = _read_json_request(
        _ACTIVITY_UFO_REPORTS_URL,
        expected_host=parsed_url.hostname,
        maximum_response_bytes=12_000_000,
    )

    if not isinstance(payload, dict):
        raise UfoReportFeedError(
            "Activity UFO-report endpoint returned an invalid object"
        )

    report_values = payload.get("reports")

    if not isinstance(report_values, list):
        raise UfoReportFeedError(
            "Activity UFO-report endpoint did not return reports"
        )

    candidates: list[ExternalUfoReport] = []

    for value in report_values:
        if not isinstance(value, dict):
            continue

        if _bounded_text(value.get("sourceKey"), 64).casefold() != "ufosint":
            continue

        quality = _integer(value.get("qualityScore"))

        if (
            quality is None
            or quality < settings.minimum_quality_score
        ):
            continue

        try:
            observed_at = _parse_datetime(
                value.get("observedAt"),
                "observedAt",
            )
        except UfoReportFeedError:
            continue

        if observed_at > now + timedelta(minutes=15):
            continue

        indexed_value = value.get("indexedAt")

        try:
            indexed_at = (
                _parse_datetime(indexed_value, "indexedAt")
                if indexed_value
                else now
            )
        except UfoReportFeedError:
            indexed_at = now

        report_id = _bounded_text(
            value.get("reportId"),
            180,
        )

        if not report_id:
            continue

        summary = _sanitize_witness_summary(
            value.get("summary"),
            8_000,
        )

        title = _bounded_text(
            value.get("title"),
            500,
        )

        if not title:
            title = "UFOSINT observation"

        location_name = _bounded_text(
            value.get("locationName"),
            300,
        ) or "Location unavailable"

        precision = _bounded_text(
            value.get("coordinatePrecision"),
            80,
        ) or "unknown"

        latitude = _number(value.get("latitude"))
        longitude = _number(value.get("longitude"))

        candidates.append(
            ExternalUfoReport(
                report_id=report_id,
                source_key="ufosint",
                source_name=(
                    _bounded_text(
                        value.get("sourceName"),
                        180,
                    )
                    or "UFOSINT Explorer"
                ),
                source_page_url=_UFOSINT_PAGE_URL,
                source_url=_optional_source_url(
                    value.get("sourceUrl"),
                    source_page_url=_UFOSINT_PAGE_URL,
                ),
                authorization_mode="api",
                observed_at=observed_at,
                indexed_at=indexed_at,
                latitude=latitude if latitude is not None else 0.0,
                longitude=longitude if longitude is not None else 0.0,
                title=title,
                location_name=location_name,
                coordinate_precision=precision,
                summary=summary,
                status=(
                    _bounded_text(
                        value.get("status"),
                        80,
                    )
                    or "unverified"
                ),
                quality_score=quality,
            )
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=_report_recency_key,
    )



def _fetch_approved_json_feed(settings: UfoReportSettings) -> UfoReportFeed:
    if settings.feed_url is None:
        raise UfoReportFeedError("approved JSON feed URL is missing")
    return parse_ufo_report_feed(
        _read_json_request(settings.feed_url),
        minimum_quality_score=settings.minimum_quality_score,
    )


class UfoReportFeedService:
    def __init__(self, settings: UfoReportSettings) -> None:
        self.settings = settings
        self._initialized = False
        self._seen_ids: list[str] = []
        self._seen_set: set[str] = set()
        self._load_state()

    def _load_state(self) -> None:
        try:
            value = json.loads(self.settings.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(value, dict) or value.get("schemaVersion") not in {
            "1.0.0",
            "2.0.0",
        }:
            return
        self._initialized = bool(value.get("initialized"))
        seen = value.get("seenIds")
        if not isinstance(seen, list):
            return
        self._seen_ids = [
            item
            for item in seen[-_MAX_SEEN_IDS:]
            if isinstance(item, str) and 0 < len(item) <= 256
        ]
        self._seen_set = set(self._seen_ids)

    def _save_state(self) -> None:
        path = self.settings.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": "2.0.0",
            "initialized": self._initialized,
            "sourceMode": self.settings.source_mode,
            "minimumQualityScore": self.settings.minimum_quality_score,
            "seenIds": self._seen_ids[-_MAX_SEEN_IDS:],
        }
        handle, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    async def latest_qualifying_reports(
        self,
    ) -> tuple[ExternalUfoReport, ...]:
        if not self.settings.enabled:
            raise UfoReportFeedError(
                "UFO report polling is disabled"
            )

        if self.settings.source_mode != "ufosint":
            raise UfoReportFeedError(
                "latest qualifying report is only "
                "available in UFOSINT mode"
            )

        feed = await asyncio.to_thread(
            _fetch_ufosint_feed,
            self.settings,
        )
        candidates = tuple(
            report
            for report in feed.reports
            if report.quality_score >= self.settings.minimum_quality_score
        )
        return tuple(
            sorted(
                candidates,
                key=_report_recency_key,
                reverse=True,
            )
        )

    async def latest_qualifying_report(
        self,
    ) -> ExternalUfoReport | None:
        reports = await self.latest_qualifying_reports()
        return reports[0] if reports else None

    async def poll(self) -> UfoReportPoll:
        if not self.settings.enabled:
            raise UfoReportFeedError("UFO report polling is disabled")
        fetcher = (
            _fetch_ufosint_feed
            if self.settings.source_mode == "ufosint"
            else _fetch_approved_json_feed
        )
        source_feed = await asyncio.to_thread(fetcher, self.settings)
        # Second defensive quality gate. No record <=50 can be mapped or spoken.
        feed = UfoReportFeed(
            source_key=source_feed.source_key,
            source_name=source_feed.source_name,
            source_page_url=source_feed.source_page_url,
            license_text=source_feed.license_text,
            authorization_mode=source_feed.authorization_mode,
            retrieved_at=source_feed.retrieved_at,
            reports=tuple(
                report
                for report in source_feed.reports
                if report.quality_score >= self.settings.minimum_quality_score
            ),
        )
        first_successful_poll = not self._initialized
        if first_successful_poll:
            self._initialized = True
            if not self.settings.state_path.exists():
                self._save_state()
        unseen = tuple(
            sorted(
                (
                    report
                    for report in feed.reports
                    if f"{report.source_key}:{report.report_id}" not in self._seen_set
                ),
                key=_report_recency_key,
                reverse=True,
            )
        )
        return UfoReportPoll(
            feed=feed,
            first_successful_poll=first_successful_poll,
            unseen_reports=unseen,
        )

    def is_seen(self, report: ExternalUfoReport) -> bool:
        return f"{report.source_key}:{report.report_id}" in self._seen_set

    def mark_seen(self, reports: Iterable[ExternalUfoReport]) -> None:
        changed = False
        for report in reports:
            identifier = f"{report.source_key}:{report.report_id}"
            if identifier in self._seen_set:
                continue
            self._seen_set.add(identifier)
            self._seen_ids.append(identifier)
            changed = True
        if len(self._seen_ids) > _MAX_SEEN_IDS:
            self._seen_ids = self._seen_ids[-_MAX_SEEN_IDS:]
            self._seen_set = set(self._seen_ids)
            changed = True
        if changed or not self.settings.state_path.exists():
            self._save_state()
