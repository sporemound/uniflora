from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SHA256_LENGTH = 64
REQUIRED_SIGNAL_COLUMNS = (
    "sample_index",
    "offset_seconds",
    "raw_voltage_v",
    "calibrated_voltage_v",
    "uncertainty_v",
    "quality",
)


class ArtifactValidationError(ValueError):
    """Raised when a dashboard artifact is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class EventMarker:
    event_id: str
    label: str
    offset_seconds: float
    source: str
    uncertainty_seconds: float

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> EventMarker:
        return cls(
            event_id=_required_text(value, "event_id"),
            label=_required_text(value, "label"),
            offset_seconds=float(value["offset_seconds"]),
            source=_required_text(value, "source"),
            uncertainty_seconds=float(value.get("uncertainty_seconds", 0.0)),
        )


@dataclass(frozen=True)
class DerivedValue:
    value_id: str
    label: str
    value: float
    unit: str
    uncertainty: float | None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> DerivedValue:
        uncertainty = value.get("uncertainty")
        return cls(
            value_id=_required_text(value, "value_id"),
            label=_required_text(value, "label"),
            value=float(value["value"]),
            unit=_required_text(value, "unit"),
            uncertainty=None if uncertainty is None else float(uncertainty),
        )


@dataclass(frozen=True)
class AnalysisMethod:
    method_id: str
    version: str
    parameters: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> AnalysisMethod:
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ArtifactValidationError("method.parameters must be an object")
        return cls(
            method_id=_required_text(value, "method_id"),
            version=_required_text(value, "version"),
            parameters=parameters,
        )


@dataclass(frozen=True)
class AnalysisArtifact:
    schema_version: str
    artifact_id: str
    environment: str
    position_id: str
    institution_id: str
    title: str
    completed_at: datetime
    state_head_hash: str
    reference_time_utc: datetime
    facility_timezone: str
    source_timezone: str
    source_clock_id: str
    data_file: str
    data_sha256: str
    sample_rate_hz: float
    method: AnalysisMethod
    events: tuple[EventMarker, ...]
    derived_values: tuple[DerivedValue, ...]
    limitations: tuple[str, ...]
    public_summary: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> AnalysisArtifact:
        environment = _required_text(value, "environment")
        if environment not in {"live", "test"}:
            raise ArtifactValidationError("environment must be live or test")

        state_head_hash = _required_text(value, "state_head_hash").lower()
        data_sha256 = _required_text(value, "data_sha256").lower()
        _validate_sha256(state_head_hash, "state_head_hash")
        _validate_sha256(data_sha256, "data_sha256")

        events_raw = value.get("events", [])
        derived_raw = value.get("derived_values", [])
        limitations_raw = value.get("limitations", [])
        if not isinstance(events_raw, list) or not events_raw:
            raise ArtifactValidationError("events must be a non-empty list")
        if not isinstance(derived_raw, list):
            raise ArtifactValidationError("derived_values must be a list")
        if not isinstance(limitations_raw, list) or not limitations_raw:
            raise ArtifactValidationError("limitations must be a non-empty list")

        sample_rate_hz = float(value["sample_rate_hz"])
        if sample_rate_hz <= 0:
            raise ArtifactValidationError("sample_rate_hz must be positive")

        return cls(
            schema_version=_required_text(value, "schema_version"),
            artifact_id=_required_text(value, "artifact_id"),
            environment=environment,
            position_id=_required_text(value, "position_id"),
            institution_id=_required_text(value, "institution_id"),
            title=_required_text(value, "title"),
            completed_at=_parse_datetime(value["completed_at"], "completed_at"),
            state_head_hash=state_head_hash,
            reference_time_utc=_parse_datetime(
                value["reference_time_utc"], "reference_time_utc"
            ),
            facility_timezone=_required_text(value, "facility_timezone"),
            source_timezone=_required_text(value, "source_timezone"),
            source_clock_id=_required_text(value, "source_clock_id"),
            data_file=_required_text(value, "data_file"),
            data_sha256=data_sha256,
            sample_rate_hz=sample_rate_hz,
            method=AnalysisMethod.from_mapping(_required_mapping(value, "method")),
            events=tuple(EventMarker.from_mapping(item) for item in events_raw),
            derived_values=tuple(DerivedValue.from_mapping(item) for item in derived_raw),
            limitations=tuple(
                _nonempty_string(item, "limitations item") for item in limitations_raw
            ),
            public_summary=_required_text(value, "public_summary"),
        )

    def canonical_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "environment": self.environment,
            "position_id": self.position_id,
            "institution_id": self.institution_id,
            "title": self.title,
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "state_head_hash": self.state_head_hash,
            "reference_time_utc": self.reference_time_utc.isoformat().replace("+00:00", "Z"),
            "facility_timezone": self.facility_timezone,
            "source_timezone": self.source_timezone,
            "source_clock_id": self.source_clock_id,
            "data_file": self.data_file,
            "data_sha256": self.data_sha256,
            "sample_rate_hz": self.sample_rate_hz,
            "method": {
                "method_id": self.method.method_id,
                "version": self.method.version,
                "parameters": self.method.parameters,
            },
            "events": [
                {
                    "event_id": event.event_id,
                    "label": event.label,
                    "offset_seconds": event.offset_seconds,
                    "source": event.source,
                    "uncertainty_seconds": event.uncertainty_seconds,
                }
                for event in self.events
            ],
            "derived_values": [
                {
                    "value_id": item.value_id,
                    "label": item.label,
                    "value": item.value,
                    "unit": item.unit,
                    "uncertainty": item.uncertainty,
                }
                for item in self.derived_values
            ],
            "limitations": list(self.limitations),
            "public_summary": self.public_summary,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_mapping(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def artifact_definition_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def load_artifact(path: Path) -> AnalysisArtifact:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactValidationError(f"Artifact file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactValidationError(f"Artifact JSON is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactValidationError("Artifact root must be an object")
    return AnalysisArtifact.from_mapping(value)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ArtifactValidationError(f"{key} must be an object")
    return item


def _required_text(value: dict[str, Any], key: str) -> str:
    return _nonempty_string(value.get(key), key)


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_datetime(value: Any, label: str) -> datetime:
    text = _nonempty_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactValidationError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ArtifactValidationError(f"{label} must include a time zone")
    return parsed


def _validate_sha256(value: str, label: str) -> None:
    is_invalid = len(value) != SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    )
    if is_invalid:
        raise ArtifactValidationError(f"{label} must be lowercase SHA-256 hex")
