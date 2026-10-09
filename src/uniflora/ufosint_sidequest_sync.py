"""Signed, fail-closed synchronization for UFOSINT Dynamical sidequests.

The module deliberately provides no HTTP implementation and no weather provider.
Callers must inject both boundaries.  A synchronization cycle therefore cannot make
an implicit network request, and an unavailable adapter result is never published as
an evidence artifact.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from uniflora.dynamical_context import (
    DATASET_QUERY_ORDER,
    NON_CAUSAL_SCOPE,
    SUPPORTED_DATASETS,
    HistoricalWeatherError,
    HistoricalWeatherRequest,
    OptionalWeatherQueryAdapter,
    WeatherEvidenceArtifact,
    canonical_json_bytes,
    plan_historical_weather,
)

JOB_RESPONSE_SCHEMA_VERSION = "1.0.0"
REPORT_SNAPSHOT_SCHEMA_VERSION = "1.0.0"
SYNC_IMPLEMENTATION_VERSION = "1"
DEFAULT_CITY_UNCERTAINTY_KM = 50.0
MAX_JOBS_PER_CYCLE = 25
MAX_RESPONSE_BYTES = 1_048_576

_JOBS_PATH = "/api/hypha/ufosint-sidequests/jobs"
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,160}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_UFOSINT_REPORT_ID_PATTERN = re.compile(r"^ufosint:[1-9][0-9]{0,18}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991

_REPORT_KEYS = frozenset(
    {
        "schemaVersion",
        "sourceKey",
        "reportId",
        "sourceName",
        "sourcePageUrl",
        "sourceUrl",
        "observedAt",
        "indexedAt",
        "latitude",
        "longitude",
        "title",
        "locationName",
        "coordinatePrecision",
        "summary",
        "status",
        "qualityScore",
    }
)
_TIME_UNCERTAINTY_KEYS = frozenset(
    {"basis", "reportDay", "dayUncertaintyDays"}
)
_JOB_KEYS = frozenset(
    {
        "sidequestId",
        "revision",
        "completedDatasetKeys",
        "requiredDatasetKeys",
        "reportSnapshotSha256",
        "reportSnapshot",
        "timeUncertainty",
    }
)
_JOB_RESPONSE_KEYS = frozenset({"schemaVersion", "jobs"})
_RECEIPT_KEYS = frozenset({"ok", "sidequestId", "revision", "artifactId"})


class SidequestSyncError(RuntimeError):
    """Raised when a signed sync or response-contract operation fails."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status = status


@dataclass(frozen=True, slots=True)
class SidequestHttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] | None = None


class SidequestHttpTransport(Protocol):
    """Explicit HTTP boundary; the sync module supplies no default implementation."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> SidequestHttpResponse: ...


class WeatherArtifactAdapter(Protocol):
    def query(
        self,
        plan: object,
        step: object,
        *,
        retrieved_at: datetime,
    ) -> WeatherEvidenceArtifact: ...


def _require_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise SidequestSyncError(
            f"{label} has an invalid shape ({'; '.join(details)}).",
            operation="response contract",
        )


def _record(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise SidequestSyncError(
            f"{label} must be a JSON object.",
            operation="response contract",
        )
    return cast(Mapping[str, object], value)


def _text(value: object, maximum: int, *, label: str) -> str:
    if not isinstance(value, str):
        raise SidequestSyncError(
            f"{label} must be text.",
            operation="response contract",
        )
    normalized = " ".join(value.replace("\x00", " ").split())
    if not normalized or len(normalized) > maximum or normalized != value:
        raise SidequestSyncError(
            f"{label} is empty, overlong, or not normalized.",
            operation="response contract",
        )
    return normalized


def _identifier(value: object, *, label: str) -> str:
    parsed = _text(value, 128, label=label)
    if not _IDENTIFIER_PATTERN.fullmatch(parsed):
        raise SidequestSyncError(
            f"{label} contains unsupported characters.",
            operation="response contract",
        )
    return parsed


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise SidequestSyncError(
            f"{label} must be a lowercase SHA-256 digest.",
            operation="response contract",
        )
    return value


def _safe_integer(value: object, *, label: str, minimum: int = 0) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _MAX_SAFE_INTEGER
    ):
        raise SidequestSyncError(
            f"{label} must be a safe integer of at least {minimum}.",
            operation="response contract",
        )
    return value


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SidequestSyncError(
            f"{label} must be a finite number.",
            operation="response contract",
        )
    parsed = float(value)
    if not math.isfinite(parsed):
        raise SidequestSyncError(
            f"{label} must be a finite number.",
            operation="response contract",
        )
    return parsed


def _timestamp(value: object, *, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or "T" not in value:
        raise SidequestSyncError(
            f"{label} must be an ISO-8601 timestamp.",
            operation="response contract",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SidequestSyncError(
            f"{label} must be an ISO-8601 timestamp.",
            operation="response contract",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SidequestSyncError(
            f"{label} must include a UTC offset.",
            operation="response contract",
        )
    return value, parsed.astimezone(UTC)


def _date(value: object, *, label: str) -> date:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise SidequestSyncError(
            f"{label} must be an ISO calendar date.",
            operation="response contract",
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SidequestSyncError(
            f"{label} must be an ISO calendar date.",
            operation="response contract",
        ) from exc


def _https_url(value: object, *, label: str, ufosint_only: bool = False) -> str:
    parsed_value = _text(value, 2_000, label=label)
    parsed = urlsplit(parsed_value)
    host = (parsed.hostname or "").casefold().removeprefix("www.").rstrip(".")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (ufosint_only and host != "ufosint.com")
    ):
        raise SidequestSyncError(
            f"{label} must use an approved HTTPS URL.",
            operation="response contract",
        )
    return parsed_value


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SidequestSyncError(
            "Injected clock must return a timezone-aware datetime.",
            operation="analysis",
        )
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class UfosintReportSnapshot:
    """Validated immutable subset copied from the existing Activity sidequest schema."""

    schema_version: Literal["1.0.0"]
    source_key: Literal["ufosint"]
    report_id: str
    source_name: str
    source_page_url: str
    source_url: str | None
    observed_at: str
    indexed_at: str
    latitude: float
    longitude: float
    title: str
    location_name: str
    coordinate_precision: str
    summary: str
    status: Literal["unverified"]
    quality_score: int

    @property
    def observed_day_utc(self) -> date:
        return _timestamp(self.observed_at, label="report observed time")[1].date()

    def to_record(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "sourceKey": self.source_key,
            "reportId": self.report_id,
            "sourceName": self.source_name,
            "sourcePageUrl": self.source_page_url,
            "sourceUrl": self.source_url,
            "observedAt": self.observed_at,
            "indexedAt": self.indexed_at,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "title": self.title,
            "locationName": self.location_name,
            "coordinatePrecision": self.coordinate_precision,
            "summary": self.summary,
            "status": self.status,
            "qualityScore": self.quality_score,
        }


def _parse_report_snapshot(value: object) -> UfosintReportSnapshot:
    raw = _record(value, label="report snapshot")
    _require_exact_keys(raw, _REPORT_KEYS, label="report snapshot")
    if raw["schemaVersion"] != REPORT_SNAPSHOT_SCHEMA_VERSION:
        raise SidequestSyncError(
            "Report snapshot schema is unsupported.",
            operation="response contract",
        )
    if raw["sourceKey"] != "ufosint" or raw["status"] != "unverified":
        raise SidequestSyncError(
            "Job is not scoped to an unverified UFOSINT report.",
            operation="response contract",
        )
    observed_text, observed_at = _timestamp(
        raw["observedAt"], label="report observed time"
    )
    indexed_text, indexed_at = _timestamp(raw["indexedAt"], label="report indexed time")
    if observed_at.timestamp() > indexed_at.timestamp() + 15 * 60:
        raise SidequestSyncError(
            "Report observed time is later than its indexed time.",
            operation="response contract",
        )
    latitude = _number(raw["latitude"], label="report latitude")
    longitude = _number(raw["longitude"], label="report longitude")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise SidequestSyncError(
            "Report coordinates are outside WGS84 bounds.",
            operation="response contract",
        )
    if any(
        abs(coordinate / 0.05 - round(coordinate / 0.05)) >= 1e-7
        for coordinate in (latitude, longitude)
    ):
        raise SidequestSyncError(
            "Report coordinates are not on the public 0.05-degree grid.",
            operation="response contract",
        )
    quality_score = _safe_integer(
        raw["qualityScore"], label="report quality score", minimum=51
    )
    if quality_score > 100:
        raise SidequestSyncError(
            "Report quality score exceeds 100.",
            operation="response contract",
        )
    source_url_value = raw["sourceUrl"]
    source_url = (
        None
        if source_url_value is None
        else _https_url(source_url_value, label="UFOSINT report URL", ufosint_only=True)
    )
    report_id = _text(raw["reportId"], 180, label="report ID")
    if not _UFOSINT_REPORT_ID_PATTERN.fullmatch(report_id):
        raise SidequestSyncError(
            "Report ID is not a canonical UFOSINT report identifier.",
            operation="response contract",
        )
    return UfosintReportSnapshot(
        schema_version="1.0.0",
        source_key="ufosint",
        report_id=report_id,
        source_name=_text(raw["sourceName"], 180, label="report source name"),
        source_page_url=_https_url(
            raw["sourcePageUrl"],
            label="UFOSINT source page URL",
            ufosint_only=True,
        ),
        source_url=source_url,
        observed_at=observed_text,
        indexed_at=indexed_text,
        latitude=latitude,
        longitude=longitude,
        title=_text(raw["title"], 180, label="report title"),
        location_name=_text(raw["locationName"], 180, label="report location"),
        coordinate_precision=_text(
            raw["coordinatePrecision"], 64, label="coordinate precision"
        ),
        summary=_text(raw["summary"], 2_000, label="report summary"),
        status="unverified",
        quality_score=quality_score,
    )


@dataclass(frozen=True, slots=True)
class DateOnlyUncertainty:
    basis: Literal["day_only"]
    report_day: date
    day_uncertainty_days: int

    def to_record(self) -> dict[str, object]:
        return {
            "basis": self.basis,
            "reportDay": self.report_day.isoformat(),
            "dayUncertaintyDays": self.day_uncertainty_days,
        }


@dataclass(frozen=True, slots=True)
class UfosintSidequestJob:
    sidequest_id: str
    revision: int
    completed_dataset_keys: tuple[str, ...]
    required_dataset_keys: tuple[str, ...]
    report_snapshot_sha256: str
    report_snapshot: UfosintReportSnapshot
    time_uncertainty: DateOnlyUncertainty

    def historical_weather_request(self) -> HistoricalWeatherRequest:
        return HistoricalWeatherRequest.from_ufosint_city(
            report_id=self.report_snapshot.report_id,
            report_day=self.time_uncertainty.report_day,
            latitude=self.report_snapshot.latitude,
            longitude=self.report_snapshot.longitude,
            city_uncertainty_km=DEFAULT_CITY_UNCERTAINTY_KM,
            day_uncertainty_days=self.time_uncertainty.day_uncertainty_days,
        )


@dataclass(frozen=True, slots=True)
class SidequestJobBatch:
    schema_version: Literal["1.0.0"]
    jobs: tuple[UfosintSidequestJob, ...]


def _parse_dataset_keys(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > len(DATASET_QUERY_ORDER):
        raise SidequestSyncError(
            f"{label} must be a bounded JSON array.",
            operation="response contract",
        )
    keys: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in SUPPORTED_DATASETS:
            raise SidequestSyncError(
                f"{label} contains an unsupported Dynamical dataset key.",
                operation="response contract",
            )
        keys.append(item)
    if len(keys) != len(set(keys)):
        raise SidequestSyncError(
            f"{label} contains duplicate dataset keys.",
            operation="response contract",
        )
    return tuple(keys)


def _parse_job(value: object) -> UfosintSidequestJob:
    raw = _record(value, label="sidequest job")
    _require_exact_keys(raw, _JOB_KEYS, label="sidequest job")
    report_raw = _record(raw["reportSnapshot"], label="report snapshot")
    report_hash = _sha256(raw["reportSnapshotSha256"], label="report snapshot hash")
    actual_hash = hashlib.sha256(canonical_json_bytes(report_raw)).hexdigest()
    if actual_hash != report_hash:
        raise SidequestSyncError(
            "Report snapshot does not match its immutable content hash.",
            operation="response contract",
        )
    report = _parse_report_snapshot(report_raw)
    uncertainty_raw = _record(raw["timeUncertainty"], label="time uncertainty")
    _require_exact_keys(
        uncertainty_raw,
        _TIME_UNCERTAINTY_KEYS,
        label="time uncertainty",
    )
    if uncertainty_raw["basis"] != "day_only":
        raise SidequestSyncError(
            "UFOSINT analysis jobs must use date-only event uncertainty.",
            operation="response contract",
        )
    report_day = _date(uncertainty_raw["reportDay"], label="uncertain report day")
    if report_day != report.observed_day_utc:
        raise SidequestSyncError(
            "Date-only job scope does not match the immutable report snapshot.",
            operation="response contract",
        )
    uncertainty_days = _safe_integer(
        uncertainty_raw["dayUncertaintyDays"],
        label="day uncertainty",
        minimum=1,
    )
    if uncertainty_days > 7:
        raise SidequestSyncError(
            "Day uncertainty exceeds the supported seven-day bound.",
            operation="response contract",
        )
    completed_dataset_keys = _parse_dataset_keys(
        raw["completedDatasetKeys"],
        label="completed dataset keys",
    )
    required_dataset_keys = _parse_dataset_keys(
        raw["requiredDatasetKeys"],
        label="required dataset keys",
    )
    if not set(completed_dataset_keys).issubset(required_dataset_keys):
        raise SidequestSyncError(
            "Completed dataset keys must be a subset of required dataset keys.",
            operation="response contract",
        )
    return UfosintSidequestJob(
        sidequest_id=_identifier(raw["sidequestId"], label="sidequest ID"),
        revision=_safe_integer(raw["revision"], label="sidequest revision", minimum=1),
        completed_dataset_keys=completed_dataset_keys,
        required_dataset_keys=required_dataset_keys,
        report_snapshot_sha256=report_hash,
        report_snapshot=report,
        time_uncertainty=DateOnlyUncertainty(
            basis="day_only",
            report_day=report_day,
            day_uncertainty_days=uncertainty_days,
        ),
    )


def parse_job_response(value: object) -> SidequestJobBatch:
    """Strictly parse a signed pending-job response."""

    raw = _record(value, label="job response")
    _require_exact_keys(raw, _JOB_RESPONSE_KEYS, label="job response")
    if raw["schemaVersion"] != JOB_RESPONSE_SCHEMA_VERSION:
        raise SidequestSyncError(
            "Job response schema is unsupported.",
            operation="response contract",
        )
    jobs_value = raw["jobs"]
    if not isinstance(jobs_value, list) or len(jobs_value) > MAX_JOBS_PER_CYCLE:
        raise SidequestSyncError(
            f"Job response must contain at most {MAX_JOBS_PER_CYCLE} jobs.",
            operation="response contract",
        )
    jobs = tuple(_parse_job(item) for item in jobs_value)
    sidequest_ids = tuple(job.sidequest_id for job in jobs)
    if len(sidequest_ids) != len(set(sidequest_ids)):
        raise SidequestSyncError(
            "Job response contains duplicate sidequest IDs.",
            operation="response contract",
        )
    return SidequestJobBatch(schema_version="1.0.0", jobs=jobs)


@dataclass(frozen=True, slots=True)
class ActivityArtifactProjection:
    """Immutable serialized Activity metadata plus the hashed evidence content."""

    artifact_id: str
    content_sha256: str
    content: bytes
    metadata_json: bytes

    def to_record(self) -> dict[str, object]:
        decoded = json.loads(self.metadata_json)
        if not isinstance(decoded, dict):  # pragma: no cover - construction invariant
            raise SidequestSyncError(
                "Projected artifact metadata is not an object.",
                operation="artifact projection",
            )
        return cast(dict[str, object], decoded)


def _unique_bounded_text(
    values: tuple[str, ...],
    *,
    maximum_items: int,
    maximum_length: int,
    label: str,
) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.replace("\x00", " ").split())
        if not normalized or len(normalized) > maximum_length:
            raise SidequestSyncError(
                f"{label} contains empty or overlong text.",
                operation="artifact projection",
            )
        if normalized not in result:
            result.append(normalized)
    if not result or len(result) > maximum_items:
        raise SidequestSyncError(
            f"{label} must contain between 1 and {maximum_items} unique entries.",
            operation="artifact projection",
        )
    return result


def project_dynamical_analysis(
    job: UfosintSidequestJob,
    evidence: WeatherEvidenceArtifact,
) -> ActivityArtifactProjection:
    """Project an available weather artifact into the shared Activity metadata schema."""

    if evidence.status != "available":
        raise SidequestSyncError(
            "Unavailable evidence may not be attached to an Activity sidequest.",
            operation="artifact projection",
        )
    if evidence.report_id != job.report_snapshot.report_id:
        raise SidequestSyncError(
            "Weather evidence references a different UFOSINT report.",
            operation="artifact projection",
        )
    definition = SUPPORTED_DATASETS.get(evidence.dataset_key)
    if definition is None:
        raise SidequestSyncError(
            "Weather evidence uses an unsupported Dynamical dataset.",
            operation="artifact projection",
        )

    content = canonical_json_bytes(evidence)
    content_sha256 = hashlib.sha256(content).hexdigest()
    if content_sha256 != evidence.artifact_hash:
        raise SidequestSyncError(
            "Weather evidence content hash is internally inconsistent.",
            operation="artifact projection",
        )
    artifact_id = f"dynamical:{evidence.dataset_key}:{content_sha256[:24]}"
    _identifier(artifact_id, label="artifact ID")

    retrieved_at = _iso_utc(evidence.provenance.retrieved_at)
    external_sources = [definition.catalog_url]
    if definition.stac_url is not None:
        external_sources.append(definition.stac_url)
    external_sources.extend(evidence.provenance.source_assets)
    external_sources = list(dict.fromkeys(external_sources))
    if len(external_sources) + 1 > 32:
        raise SidequestSyncError(
            "Artifact has too many provenance inputs for the Activity contract.",
            operation="artifact projection",
        )
    provenance: list[dict[str, object]] = [
        {
            "provenanceId": f"report:{job.report_snapshot_sha256[:24]}",
            "parentType": "report_snapshot",
            "parentReference": job.report_snapshot.report_id,
            "parentContentSha256": job.report_snapshot_sha256,
            "relation": "derived_from",
            "description": (
                "Pins the immutable, privacy-reduced UFOSINT report snapshot that scoped "
                "this date-only historical-weather query."
            ),
            "retrievedAt": None,
        }
    ]
    for index, source in enumerate(external_sources, start=1):
        _https_url(source, label=f"external provenance source {index}")
        provenance.append(
            {
                "provenanceId": f"source:{index:02d}",
                "parentType": "external_source",
                "parentReference": source,
                "parentContentSha256": None,
                "relation": "contextualizes",
                "description": (
                    "Dynamical catalog, STAC collection, or provider asset URL retained by "
                    "the injected adapter; no unverified content hash is asserted."
                ),
                "retrievedAt": retrieved_at,
            }
        )

    limitations = _unique_bounded_text(
        (*evidence.limitations, NON_CAUSAL_SCOPE),
        maximum_items=16,
        maximum_length=1_000,
        label="dynamical limitations",
    )
    temporal = evidence.temporal_envelope.to_record()
    spatial = evidence.spatial_envelope.to_record()
    coordinate_uncertainty = (
        f"Privacy-reduced {job.report_snapshot.coordinate_precision} coordinate; the query "
        "uses the recorded spatial envelope rather than an exact witness position."
    )
    date_uncertainty = (
        "UFOSINT supplies a report date, not an authoritative event time; the query uses "
        f"a plus-or-minus {job.time_uncertainty.day_uncertainty_days}-day UTC buffer."
    )

    software_versions: list[dict[str, str]] = [
        {"name": "uniflora.ufosint_sidequest_sync", "version": SYNC_IMPLEMENTATION_VERSION},
        {"name": "uniflora.dynamical_context", "version": str(evidence.schema_version)},
    ]
    if evidence.provenance.adapter_name not in {
        item["name"] for item in software_versions
    }:
        software_versions.append(
            {
                "name": evidence.provenance.adapter_name,
                "version": evidence.provenance.adapter_version,
            }
        )

    metadata: dict[str, object] = {
        "artifactId": artifact_id,
        "kind": "dynamical_analysis",
        "title": f"Historical weather context — {definition.title}",
        "mediaType": "application/vnd.uniflora.dynamical-context+json;version=1",
        "contentSha256": content_sha256,
        "byteLength": len(content),
        "artifactUri": None,
        "dynamicalAnalysis": {
            "modelId": f"dynamical_context:{evidence.dataset_key}",
            "modelVersion": str(evidence.schema_version),
            "implementation": (
                "uniflora.dynamical_context.OptionalWeatherQueryAdapter with an explicitly "
                "injected provider query function"
            ),
            "coordinateFrame": "WGS 84 geographic coordinates (EPSG:4326)",
            "timeStandard": "UTC; event time intentionally treated as date-only",
            "timeWindowStart": temporal["start"],
            "timeWindowEnd": temporal["end_exclusive"],
            "initialConditions": [
                {
                    "name": "report_day",
                    "value": job.time_uncertainty.report_day.isoformat(),
                    "unit": None,
                    "uncertainty": date_uncertainty,
                },
                {
                    "name": "report_latitude",
                    "value": job.report_snapshot.latitude,
                    "unit": "degree_north",
                    "uncertainty": coordinate_uncertainty,
                },
                {
                    "name": "report_longitude",
                    "value": job.report_snapshot.longitude,
                    "unit": "degree_east",
                    "uncertainty": coordinate_uncertainty,
                },
            ],
            "parameters": [
                {
                    "name": "dataset_key",
                    "value": evidence.dataset_key,
                    "unit": None,
                    "uncertainty": None,
                },
                {
                    "name": "request_sha256",
                    "value": evidence.request_hash,
                    "unit": None,
                    "uncertainty": None,
                },
                {
                    "name": "plan_sha256",
                    "value": evidence.plan_hash,
                    "unit": None,
                    "uncertainty": None,
                },
                *(
                    {
                        "name": f"spatial_{name}",
                        "value": value,
                        "unit": "degree",
                        "uncertainty": coordinate_uncertainty,
                    }
                    for name, value in spatial.items()
                ),
            ],
            "derivedValues": [
                {
                    "name": "evidence_value_count",
                    "value": len(evidence.data),
                    "unit": "count",
                    "uncertainty": (
                        "Count of validated values in the hashed provider-neutral payload."
                    ),
                },
                {
                    "name": "source_asset_count",
                    "value": len(evidence.provenance.source_assets),
                    "unit": "count",
                    "uncertainty": "Only URLs retained by the injected adapter are counted.",
                },
            ],
            "assumptions": [
                "The UFOSINT observedAt value is interpreted as an event date only.",
                (
                    "Privacy-reduced coordinates scope a contextual weather query and are "
                    "not treated as an exact witness location."
                ),
                (
                    "Provider values are contextual measurements or analyses and are not a "
                    "causal classification of the reported observation."
                ),
            ],
            "uncertaintyStatements": [date_uncertainty, coordinate_uncertainty],
            "limitations": limitations,
            "softwareVersions": software_versions,
        },
        "provenance": provenance,
    }
    return ActivityArtifactProjection(
        artifact_id=artifact_id,
        content_sha256=content_sha256,
        content=content,
        metadata_json=canonical_json_bytes(metadata),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(response: SidequestHttpResponse, *, operation: str) -> object:
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise SidequestSyncError(
            "Activity response exceeded the configured size limit.",
            operation=operation,
            status=response.status,
        )
    try:
        return json.loads(response.body, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SidequestSyncError(
            "Activity returned invalid JSON.",
            operation=operation,
            status=response.status,
        ) from exc


@dataclass(frozen=True, slots=True)
class ArtifactAttachmentReceipt:
    sidequest_id: str
    revision: int
    artifact_id: str


class UfosintSidequestSyncClient:
    """Synchronous signed Activity client with an explicitly injected transport."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        transport: SidequestHttpTransport,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Activity base URL must be an HTTP(S) origin without a path")
        if parsed.scheme == "http" and (parsed.hostname or "").casefold() not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("Activity base URL must use HTTPS outside loopback development")
        if not secret:
            raise ValueError("Activity HMAC secret must not be empty")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._secret = secret.encode("utf-8")
        self._transport = transport
        self._clock = clock
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))

    def _signed_request(
        self,
        *,
        method: Literal["GET", "POST"],
        path: str,
        query: str = "",
        body: bytes,
    ) -> SidequestHttpResponse:
        timestamp = int(self._clock())
        nonce = self._nonce_factory()
        if not _NONCE_PATTERN.fullmatch(nonce):
            raise SidequestSyncError(
                "Nonce factory returned an invalid nonce.",
                operation="sign",
            )
        content_sha256 = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(
            (method, path, str(timestamp), nonce, content_sha256)
        )
        signature = hmac.new(
            self._secret,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Accept": "application/json",
            "X-Hypha-Timestamp": str(timestamp),
            "X-Hypha-Nonce": nonce,
            "X-Hypha-Content-SHA256": content_sha256,
            "X-Hypha-Signature": f"v1={signature}",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        try:
            response = self._transport.request(
                method=method,
                url=self._origin + path + query,
                headers=headers,
                body=body,
            )
        except Exception as exc:
            raise SidequestSyncError(
                f"Activity transport failed ({type(exc).__name__}).",
                operation="transport",
            ) from exc
        if not isinstance(response, SidequestHttpResponse):
            raise SidequestSyncError(
                "Activity transport returned an invalid response type.",
                operation="transport",
            )
        return response

    def list_jobs(self, *, limit: int = 25) -> SidequestJobBatch:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_JOBS_PER_CYCLE
        ):
            raise ValueError(
                f"Job limit must be an integer from 1 through {MAX_JOBS_PER_CYCLE}"
            )
        response = self._signed_request(
            method="GET",
            path=_JOBS_PATH,
            query=f"?limit={limit}",
            body=b"",
        )
        if response.status != 200:
            raise SidequestSyncError(
                "Activity job listing was rejected.",
                operation="list jobs",
                status=response.status,
            )
        return parse_job_response(_decode_json(response, operation="list jobs"))

    def attach_artifact(
        self,
        job: UfosintSidequestJob,
        artifact: ActivityArtifactProjection,
    ) -> ArtifactAttachmentReceipt:
        operation_id = f"attach:{artifact.artifact_id}"
        _identifier(operation_id, label="operation ID")
        path = f"/api/hypha/ufosint-sidequests/{job.sidequest_id}/artifacts"
        artifact_record = artifact.to_record()
        actual_content_sha256 = hashlib.sha256(artifact.content).hexdigest()
        if (
            artifact_record.get("artifactId") != artifact.artifact_id
            or actual_content_sha256 != artifact.content_sha256
            or artifact_record.get("contentSha256") != actual_content_sha256
            or artifact_record.get("byteLength") != len(artifact.content)
        ):
            raise SidequestSyncError(
                "Projected artifact metadata does not match its content bytes.",
                operation="attach artifact",
            )
        body = canonical_json_bytes(
            {
                "operationId": operation_id,
                "expectedRevision": job.revision,
                "artifact": artifact_record,
                "contentBase64": base64.b64encode(artifact.content).decode("ascii"),
            }
        )
        response = self._signed_request(method="POST", path=path, body=body)
        if response.status not in {200, 201}:
            raise SidequestSyncError(
                "Activity artifact attachment was rejected.",
                operation="attach artifact",
                status=response.status,
            )
        raw = _record(
            _decode_json(response, operation="attach artifact"),
            label="artifact attachment receipt",
        )
        _require_exact_keys(raw, _RECEIPT_KEYS, label="artifact attachment receipt")
        if raw["ok"] is not True:
            raise SidequestSyncError(
                "Artifact attachment receipt did not confirm success.",
                operation="attach artifact",
                status=response.status,
            )
        sidequest_id = _identifier(raw["sidequestId"], label="receipt sidequest ID")
        artifact_id = _identifier(raw["artifactId"], label="receipt artifact ID")
        revision = _safe_integer(raw["revision"], label="receipt revision", minimum=1)
        if (
            sidequest_id != job.sidequest_id
            or artifact_id != artifact.artifact_id
            or revision != job.revision + 1
        ):
            raise SidequestSyncError(
                "Artifact attachment receipt does not match the submitted operation.",
                operation="attach artifact",
                status=response.status,
            )
        return ArtifactAttachmentReceipt(
            sidequest_id=sidequest_id,
            revision=revision,
            artifact_id=artifact_id,
        )


JobOutcomeStatus = Literal["uploaded", "partial", "unavailable", "failed"]


@dataclass(frozen=True, slots=True)
class SidequestAnalysisOutcome:
    sidequest_id: str
    report_id: str
    status: JobOutcomeStatus
    attempted_dataset_keys: tuple[str, ...]
    dataset_key: str | None = None
    artifact_id: str | None = None
    revision: int | None = None
    reason: str | None = None
    uploaded_dataset_keys: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    completed_dataset_keys: tuple[str, ...] = ()
    pending_dataset_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SidequestAnalysisCycle:
    jobs_received: int
    outcomes: tuple[SidequestAnalysisOutcome, ...]

    @property
    def uploaded_count(self) -> int:
        return sum(outcome.status == "uploaded" for outcome in self.outcomes)

    @property
    def artifact_upload_count(self) -> int:
        return sum(len(outcome.artifact_ids) for outcome in self.outcomes)


class UfosintSidequestAnalysisWorker:
    """Run one bounded job-list/query/attach cycle using explicit adapters only."""

    def __init__(
        self,
        client: UfosintSidequestSyncClient,
        *,
        adapters: Mapping[str, OptionalWeatherQueryAdapter],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        unknown = set(adapters) - set(SUPPORTED_DATASETS)
        if unknown:
            raise ValueError(f"Unsupported adapter dataset keys: {', '.join(sorted(unknown))}")
        self._client = client
        self._adapters = dict(adapters)
        self._clock = clock

    def run_cycle(self, *, limit: int = 25) -> SidequestAnalysisCycle:
        batch = self._client.list_jobs(limit=limit)
        outcomes = tuple(self._run_job(job) for job in batch.jobs)
        return SidequestAnalysisCycle(jobs_received=len(batch.jobs), outcomes=outcomes)

    def _run_job(self, job: UfosintSidequestJob) -> SidequestAnalysisOutcome:
        attempted: list[str] = []
        unavailable_codes: list[str] = []
        uploaded_dataset_keys: list[str] = []
        artifact_ids: list[str] = []
        required = set(job.required_dataset_keys)
        completed = set(job.completed_dataset_keys)
        current_job = job
        try:
            plan = plan_historical_weather(job.historical_weather_request())
            query_keys = {step.dataset_key for step in plan.query_steps}
            for step in plan.unavailable_steps:
                if step.dataset_key in required and step.dataset_key not in completed:
                    unavailable_codes.append(
                        f"{step.dataset_key}:local_plan_{step.availability_code}"
                    )
            for step in plan.query_steps:
                if step.dataset_key not in required or step.dataset_key in completed:
                    continue
                adapter = self._adapters.get(step.dataset_key)
                if adapter is None:
                    unavailable_codes.append(f"{step.dataset_key}:adapter_not_configured")
                    continue
                attempted.append(step.dataset_key)
                evidence = adapter.query(
                    plan,
                    step,
                    retrieved_at=self._clock(),
                )
                if not isinstance(evidence, WeatherEvidenceArtifact):
                    raise SidequestSyncError(
                        "Injected adapter returned an invalid artifact type.",
                        operation="analysis",
                    )
                if evidence.status != "available":
                    unavailable_codes.append(
                        f"{step.dataset_key}:{evidence.availability_code}"
                    )
                    continue
                projection = project_dynamical_analysis(current_job, evidence)
                receipt = self._client.attach_artifact(current_job, projection)
                uploaded_dataset_keys.append(step.dataset_key)
                artifact_ids.append(receipt.artifact_id)
                completed.add(step.dataset_key)
                current_job = replace(current_job, revision=receipt.revision)
            missing_from_local_plan = required - completed - query_keys
            for dataset_key in DATASET_QUERY_ORDER:
                if (
                    dataset_key in missing_from_local_plan
                    and not any(
                        code.startswith(f"{dataset_key}:") for code in unavailable_codes
                    )
                ):
                    unavailable_codes.append(f"{dataset_key}:local_plan_missing")
        except (HistoricalWeatherError, SidequestSyncError, ValueError) as exc:
            completed_ordered = tuple(
                key for key in DATASET_QUERY_ORDER if key in completed
            )
            pending_ordered = tuple(
                key for key in DATASET_QUERY_ORDER if key in required - completed
            )
            return SidequestAnalysisOutcome(
                sidequest_id=job.sidequest_id,
                report_id=job.report_snapshot.report_id,
                status="partial" if uploaded_dataset_keys else "failed",
                attempted_dataset_keys=tuple(attempted),
                dataset_key=(
                    uploaded_dataset_keys[0] if uploaded_dataset_keys else None
                ),
                artifact_id=artifact_ids[0] if artifact_ids else None,
                revision=current_job.revision if artifact_ids else None,
                reason=str(exc)[:500],
                uploaded_dataset_keys=tuple(uploaded_dataset_keys),
                artifact_ids=tuple(artifact_ids),
                completed_dataset_keys=completed_ordered,
                pending_dataset_keys=pending_ordered,
            )
        completed_ordered = tuple(key for key in DATASET_QUERY_ORDER if key in completed)
        pending_ordered = tuple(
            key for key in DATASET_QUERY_ORDER if key in required - completed
        )
        if uploaded_dataset_keys:
            reason = None
            if pending_ordered:
                reason = f"Required datasets still pending: {', '.join(pending_ordered)}."
                if unavailable_codes:
                    reason += f" Unavailable results: {', '.join(unavailable_codes)}."
            return SidequestAnalysisOutcome(
                sidequest_id=job.sidequest_id,
                report_id=job.report_snapshot.report_id,
                status="uploaded",
                attempted_dataset_keys=tuple(attempted),
                dataset_key=uploaded_dataset_keys[0],
                artifact_id=artifact_ids[0],
                revision=current_job.revision,
                reason=reason,
                uploaded_dataset_keys=tuple(uploaded_dataset_keys),
                artifact_ids=tuple(artifact_ids),
                completed_dataset_keys=completed_ordered,
                pending_dataset_keys=pending_ordered,
            )
        reason = "No uncompleted required dataset returned available data."
        if unavailable_codes:
            reason = f"Unavailable results: {', '.join(unavailable_codes)}."
        elif not pending_ordered:
            reason = "All required dataset keys were already completed; no duplicate was attached."
        return SidequestAnalysisOutcome(
            sidequest_id=job.sidequest_id,
            report_id=job.report_snapshot.report_id,
            status="unavailable",
            attempted_dataset_keys=tuple(attempted),
            reason=reason,
            completed_dataset_keys=completed_ordered,
            pending_dataset_keys=pending_ordered,
        )


__all__ = [
    "ActivityArtifactProjection",
    "ArtifactAttachmentReceipt",
    "DateOnlyUncertainty",
    "DEFAULT_CITY_UNCERTAINTY_KM",
    "JOB_RESPONSE_SCHEMA_VERSION",
    "MAX_JOBS_PER_CYCLE",
    "REPORT_SNAPSHOT_SCHEMA_VERSION",
    "SidequestAnalysisCycle",
    "SidequestAnalysisOutcome",
    "SidequestHttpResponse",
    "SidequestHttpTransport",
    "SidequestJobBatch",
    "SidequestSyncError",
    "UfosintReportSnapshot",
    "UfosintSidequestAnalysisWorker",
    "UfosintSidequestJob",
    "UfosintSidequestSyncClient",
    "parse_job_response",
    "project_dynamical_analysis",
]
