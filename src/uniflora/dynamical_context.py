"""Deterministic planning primitives for historical weather context.

This module deliberately does not import xarray, DuckDB, ``dynamical_catalog``,
or a network client.  It describes what may be queried and records what an
explicitly supplied adapter returned.  Consequently, importing or planning can
never trigger network access.

UFOSINT currently supplies an event *day* and privacy-reduced city coordinates,
not an authoritative event time or exact witness location.  Requests and plans
preserve both uncertainties.  Weather artifacts are contextual evidence only;
they do not identify a cause for a reported observation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias

CATALOG_ROOT_URL = "https://stac.dynamical.org/catalog.json"
NON_CAUSAL_SCOPE = (
    "Weather context can constrain environmental conditions in the requested area and time "
    "window; it does not establish the cause, identity, trajectory, or validity of a UFOSINT "
    "report."
)

JsonScalar: TypeAlias = str | int | float | bool | None
EvidenceValue: TypeAlias = str | int | float | bool
PlanDisposition: TypeAlias = Literal["query", "unavailable"]
ArtifactStatus: TypeAlias = Literal["available", "unavailable"]


class HistoricalWeatherError(ValueError):
    """Raised when historical-weather data violates the local evidence contract."""


def _nonblank(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalWeatherError(f"{label} must be a nonblank string")
    return value.strip()


def _identifier(value: str, *, label: str) -> str:
    normalized = _nonblank(value, label=label)
    if len(normalized) > 180 or not all(
        character.isalnum() or character in "._:-" for character in normalized
    ):
        raise HistoricalWeatherError(f"{label} contains unsupported characters")
    return normalized


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalWeatherError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    normalized = _utc(value, label="timestamp")
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_compatible(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HistoricalWeatherError("canonical JSON does not permit non-finite numbers")
        return value
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise HistoricalWeatherError("canonical JSON mapping keys must be strings")
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_compatible(item) for item in value]
    to_record = getattr(value, "to_record", None)
    if callable(to_record):
        return _json_compatible(to_record())
    raise HistoricalWeatherError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return stable UTF-8 JSON suitable for hashing and durable artifacts."""

    try:
        encoded = json.dumps(
            _json_compatible(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalWeatherError(f"value is not canonical-JSON compatible: {exc}") from exc
    return encoded.encode("utf-8")


def deterministic_hash(value: object) -> str:
    """Return a lowercase SHA-256 digest of canonical JSON."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class SpatialEnvelope:
    """A non-wrapping WGS84 longitude/latitude bounding box."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise HistoricalWeatherError("spatial envelope coordinates must be finite numbers")
        if not -180 <= self.west <= 180 or not -180 <= self.east <= 180:
            raise HistoricalWeatherError("spatial envelope longitudes must be within -180..180")
        if not -90 <= self.south <= 90 or not -90 <= self.north <= 90:
            raise HistoricalWeatherError("spatial envelope latitudes must be within -90..90")
        if self.west > self.east:
            raise HistoricalWeatherError("spatial envelope may not wrap the antimeridian")
        if self.south > self.north:
            raise HistoricalWeatherError("spatial envelope south must not exceed north")

    @classmethod
    def around_city(
        cls,
        *,
        latitude: float,
        longitude: float,
        radius_km: float = 25.0,
    ) -> SpatialEnvelope:
        """Build a conservative city-scale envelope around privacy-reduced coordinates."""

        if not isinstance(radius_km, (int, float)) or not math.isfinite(radius_km):
            raise HistoricalWeatherError("city uncertainty radius must be finite")
        if not 1 <= radius_km <= 500:
            raise HistoricalWeatherError("city uncertainty radius must be within 1..500 km")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise HistoricalWeatherError("city coordinates are outside WGS84 bounds")

        latitude_delta = radius_km / 111.32
        cosine = max(abs(math.cos(math.radians(latitude))), 0.01)
        longitude_delta = min(radius_km / (111.32 * cosine), 180.0)
        return cls(
            west=max(-180.0, longitude - longitude_delta),
            south=max(-90.0, latitude - latitude_delta),
            east=min(180.0, longitude + longitude_delta),
            north=min(90.0, latitude + latitude_delta),
        )

    def intersects(self, other: SpatialEnvelope) -> bool:
        return not (
            self.east < other.west
            or self.west > other.east
            or self.north < other.south
            or self.south > other.north
        )

    def is_within(self, other: SpatialEnvelope) -> bool:
        return (
            self.west >= other.west
            and self.east <= other.east
            and self.south >= other.south
            and self.north <= other.north
        )

    def to_record(self) -> dict[str, float]:
        return {
            "east": self.east,
            "north": self.north,
            "south": self.south,
            "west": self.west,
        }


GLOBAL_ENVELOPE = SpatialEnvelope(-180.0, -90.0, 180.0, 90.0)


@dataclass(frozen=True, slots=True)
class TemporalEnvelope:
    """A UTC interval whose end is exclusive."""

    start: datetime
    end_exclusive: datetime

    def __post_init__(self) -> None:
        start = _utc(self.start, label="temporal envelope start")
        end = _utc(self.end_exclusive, label="temporal envelope end")
        if start >= end:
            raise HistoricalWeatherError("temporal envelope start must precede its end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end_exclusive", end)

    def to_record(self) -> dict[str, str]:
        return {"end_exclusive": _iso_utc(self.end_exclusive), "start": _iso_utc(self.start)}


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Frozen metadata copied from the authoritative catalog documentation."""

    key: str
    title: str
    catalog_id: str
    stac_collection_id: str | None
    catalog_url: str
    stac_url: str | None
    access_format: str
    coverage_label: str
    coverage_envelope: SpatialEnvelope
    coverage_kind: Literal["global_grid", "regional_grid", "stations"]
    temporal_start: datetime
    temporal_end_exclusive: datetime | None
    spatial_resolution: str
    temporal_resolution: str
    variables: tuple[str, ...]
    license_id: str
    license_url: str | None
    attribution: str
    source_dependencies: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.key, "dataset key"),
            (self.catalog_id, "catalog ID"),
        ):
            _identifier(value, label=label)
        for value, label in (
            (self.title, "dataset title"),
            (self.catalog_url, "catalog URL"),
            (self.access_format, "access format"),
            (self.coverage_label, "coverage label"),
            (self.spatial_resolution, "spatial resolution"),
            (self.temporal_resolution, "temporal resolution"),
            (self.license_id, "license ID"),
            (self.attribution, "attribution"),
        ):
            _nonblank(value, label=label)
        if self.stac_collection_id is not None:
            _identifier(self.stac_collection_id, label="STAC collection ID")
        start = _utc(self.temporal_start, label="dataset temporal start")
        object.__setattr__(self, "temporal_start", start)
        if self.temporal_end_exclusive is not None:
            end = _utc(self.temporal_end_exclusive, label="dataset temporal end")
            if end <= start:
                raise HistoricalWeatherError("dataset temporal end must follow its start")
            object.__setattr__(self, "temporal_end_exclusive", end)
        if not self.variables or len(self.variables) != len(set(self.variables)):
            raise HistoricalWeatherError("dataset variables must be nonempty and unique")
        for value in (*self.variables, *self.source_dependencies, *self.limitations):
            _nonblank(value, label="dataset metadata value")

    def to_record(self) -> dict[str, object]:
        return {
            "access_format": self.access_format,
            "attribution": self.attribution,
            "catalog_id": self.catalog_id,
            "catalog_url": self.catalog_url,
            "coverage_envelope": self.coverage_envelope,
            "coverage_kind": self.coverage_kind,
            "coverage_label": self.coverage_label,
            "key": self.key,
            "license_id": self.license_id,
            "license_url": self.license_url,
            "limitations": self.limitations,
            "source_dependencies": self.source_dependencies,
            "spatial_resolution": self.spatial_resolution,
            "stac_collection_id": self.stac_collection_id,
            "stac_url": self.stac_url,
            "temporal_end_exclusive": self.temporal_end_exclusive,
            "temporal_resolution": self.temporal_resolution,
            "temporal_start": self.temporal_start,
            "title": self.title,
            "variables": self.variables,
        }


def _at_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _stac_url(collection_id: str) -> str:
    return f"https://stac.dynamical.org/{collection_id}/collection.json"


_DATASETS = {
    "asos": DatasetDefinition(
        key="asos",
        title="Global Airport Observations (ASOS/AWOS)",
        catalog_id="asos-parquet",
        stac_collection_id=None,
        catalog_url="https://dynamical.org/catalog/asos-parquet/",
        stac_url=None,
        access_format="GeoParquet, Hive-partitioned by year",
        coverage_label="Global ASOS/AWOS stations",
        coverage_envelope=GLOBAL_ENVELOPE,
        coverage_kind="stations",
        temporal_start=_at_midnight(date(1940, 1, 1)),
        temporal_end_exclusive=None,
        spatial_resolution="Irregular station points; no gridded spatial resolution",
        temporal_resolution="Hourly METAR, with station special reports possible",
        variables=(
            "valid",
            "station",
            "tmpf",
            "dwpf",
            "drct",
            "sknt",
            "gust",
            "vsby",
            "alti",
            "mslp",
            "p01i",
            "geometry",
        ),
        license_id="not-stated-on-dynamical-catalog-page",
        license_url=None,
        attribution=(
            "Iowa Environmental Mesonet observations republished by dynamical.org on "
            "Source Cooperative."
        ),
        source_dependencies=(
            "The IEM archive combines feeds including Unidata IDD, NCEI ISD, and MADIS.",
            "Nearby stations may share upstream reporting and quality-control systems.",
        ),
        limitations=(
            "This is an experimental Dynamical dataset and may change without notice.",
            "No station is guaranteed inside a privacy-expanded city envelope.",
            "Observations are published as received without Dynamical resampling, "
            "interpolation, or quality-control filtering.",
            "The Dynamical catalog page does not state a dataset license; verify the "
            "terms of the IEM and upstream source before redistribution.",
        ),
    ),
    "hrrr": DatasetDefinition(
        key="hrrr",
        title="NOAA HRRR analysis",
        catalog_id="noaa-hrrr-analysis",
        stac_collection_id="noaa-hrrr-analysis",
        catalog_url="https://dynamical.org/catalog/noaa-hrrr-analysis/",
        stac_url=_stac_url("noaa-hrrr-analysis"),
        access_format="Icechunk/Zarr through the Dynamical STAC catalog",
        coverage_label="Continental United States HRRR model domain",
        coverage_envelope=SpatialEnvelope(
            west=-134.095474243164,
            south=21.1381225585938,
            east=-60.9171943664551,
            north=52.6156539916992,
        ),
        coverage_kind="regional_grid",
        temporal_start=_at_midnight(date(2014, 10, 1)),
        temporal_end_exclusive=None,
        spatial_resolution="3 km",
        temporal_resolution="1 hour",
        variables=(
            "categorical_freezing_rain_surface",
            "categorical_ice_pellets_surface",
            "categorical_rain_surface",
            "categorical_snow_surface",
            "composite_reflectivity",
            "dew_point_temperature_2m",
            "downward_long_wave_radiation_flux_surface",
            "downward_short_wave_radiation_flux_surface",
            "geopotential_height_cloud_ceiling",
            "percent_frozen_precipitation_surface",
            "precipitable_water_atmosphere",
            "precipitation_surface",
            "pressure_reduced_to_mean_sea_level",
            "pressure_surface",
            "relative_humidity_2m",
            "snow_area_fraction_surface",
            "snow_thickness_surface",
            "snow_water_equivalent_surface",
            "snowfall_surface",
            "temperature_2m",
            "total_cloud_cover_atmosphere",
            "visible_beam_downward_solar_flux_surface",
            "wind_gust_surface",
            "wind_u_10m",
            "wind_u_80m",
            "wind_v_10m",
            "wind_v_80m",
        ),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution=(
            "NOAA NWS NCEP HRRR data processed by dynamical.org from NOAA Open Data "
            "Dissemination archives."
        ),
        source_dependencies=(
            "HRRR is a numerical model analysis initialized with radar assimilation and "
            "other observing systems.",
            "It is not independent of NOAA radar or surface observations used elsewhere "
            "in this plan.",
        ),
        limitations=(
            "The archive has significant missing source files before August 2018.",
            "Some variables are unavailable before August 2016 and missing source data "
            "are represented as NaN.",
            "A model grid value is an analysis estimate, not a direct observation at the "
            "UFOSINT location.",
        ),
    ),
    "gfs": DatasetDefinition(
        key="gfs",
        title="NOAA GFS analysis",
        catalog_id="noaa-gfs-analysis",
        stac_collection_id="noaa-gfs-analysis",
        catalog_url="https://dynamical.org/catalog/noaa-gfs-analysis/",
        stac_url=_stac_url("noaa-gfs-analysis"),
        access_format="Icechunk/Zarr through the Dynamical STAC catalog",
        coverage_label="Global GFS model grid",
        coverage_envelope=SpatialEnvelope(-180.0, -90.0, 179.75, 90.0),
        coverage_kind="global_grid",
        temporal_start=_at_midnight(date(2021, 5, 1)),
        temporal_end_exclusive=None,
        spatial_resolution="0.25 degrees (about 20 km)",
        temporal_resolution="1 hour",
        variables=(
            "categorical_freezing_rain_surface",
            "categorical_ice_pellets_surface",
            "categorical_rain_surface",
            "categorical_snow_surface",
            "downward_long_wave_radiation_flux_surface",
            "downward_short_wave_radiation_flux_surface",
            "geopotential_height_cloud_ceiling",
            "maximum_temperature_2m",
            "minimum_temperature_2m",
            "percent_frozen_precipitation_surface",
            "precipitable_water_atmosphere",
            "precipitation_surface",
            "pressure_80m",
            "pressure_reduced_to_mean_sea_level",
            "pressure_surface",
            "relative_humidity_2m",
            "temperature_2m",
            "temperature_80m",
            "total_cloud_cover_atmosphere",
            "wind_u_100m",
            "wind_u_10m",
            "wind_u_80m",
            "wind_v_100m",
            "wind_v_10m",
            "wind_v_80m",
        ),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution=(
            "NOAA NWS NCEP GFS data processed by dynamical.org from NOAA Open Data "
            "Dissemination archives."
        ),
        source_dependencies=(
            "GFS is a numerical model analysis built from assimilated observing systems.",
            "It is not an independent confirmation of surface, radar, or satellite inputs "
            "that may contribute to model initialization.",
        ),
        limitations=(
            "Coverage begins 2021-05-01 in the current Dynamical collection.",
            "The grid is coarser than city-coordinate uncertainty in many cases.",
            "A model analysis constrains plausible weather context but is not a direct "
            "observation of a reported object.",
        ),
    ),
    "mrms": DatasetDefinition(
        key="mrms",
        title="NOAA MRMS CONUS analysis, hourly",
        catalog_id="noaa-mrms-conus-analysis-hourly",
        stac_collection_id="noaa-mrms-conus-analysis-hourly",
        catalog_url="https://dynamical.org/catalog/noaa-mrms-conus-analysis-hourly/",
        stac_url=_stac_url("noaa-mrms-conus-analysis-hourly"),
        access_format="Icechunk/Zarr through the Dynamical STAC catalog",
        coverage_label="CONUS radar and multisensor analysis domain",
        coverage_envelope=SpatialEnvelope(-129.995, 20.005, -60.005, 54.995),
        coverage_kind="regional_grid",
        temporal_start=_at_midnight(date(2014, 11, 1)),
        temporal_end_exclusive=None,
        spatial_resolution="0.01 degrees (about 1 km)",
        temporal_resolution="1 hour",
        variables=(
            "categorical_precipitation_type_surface",
            "flash_qpe_ffg_max_surface",
            "precipitation_pass_1_surface",
            "precipitation_pass_2_surface",
            "precipitation_radar_only_surface",
            "precipitation_surface",
        ),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution=(
            "NOAA NWS NCEP MRMS data processed by dynamical.org from NOAA NCEP, NOAA "
            "Open Data Dissemination, and Iowa Mesonet archives."
        ),
        source_dependencies=(
            "MRMS integrates multiple radars, surface observations, numerical weather "
            "prediction, and climatology.",
            "MRMS is therefore not independent of ASOS-like observations or NOAA model "
            "products in the same plan.",
        ),
        limitations=(
            "Use over CONUS land; parts of the rectangular domain lack radar coverage.",
            "Some early hours are missing, and pass-1/pass-2 variables begin 2020-10-15.",
            "Radar or precipitation context cannot establish a causal relation to a report.",
        ),
    ),
    "imerg_late": DatasetDefinition(
        key="imerg_late",
        title="NASA IMERG analysis, late",
        catalog_id="nasa-imerg-analysis-late",
        stac_collection_id="nasa-imerg-analysis-late",
        catalog_url="https://dynamical.org/catalog/nasa-imerg-analysis-late/",
        stac_url=_stac_url("nasa-imerg-analysis-late"),
        access_format="Icechunk/Zarr through the Dynamical STAC catalog",
        coverage_label="Global NASA GPM IMERG grid",
        coverage_envelope=SpatialEnvelope(-179.95, -89.95, 179.95, 89.95),
        coverage_kind="global_grid",
        temporal_start=_at_midnight(date(1998, 1, 1)),
        temporal_end_exclusive=None,
        spatial_resolution="0.1 degrees (about 10 km)",
        temporal_resolution="30 minutes",
        variables=("precipitation_quality_index_surface", "precipitation_surface"),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution=(
            "NASA GPM IMERG data processed by dynamical.org from NASA GES DISC and PPS "
            "archives."
        ),
        source_dependencies=(
            "IMERG Late merges precipitation estimates from a changing constellation of "
            "satellite sensors.",
            "Its forward/backward propagation and shared source observations mean nearby "
            "pixels and times are not independent samples.",
        ),
        limitations=(
            "Version 07 coverage begins 1998; pre-GPM-era estimates use fewer satellites "
            "and are generally lower quality, especially at high latitudes.",
            "IMERG is a satellite precipitation estimate, not a direct local rain gauge.",
            "Precipitation presence or absence cannot establish a causal relation to a report.",
        ),
    ),
}

SUPPORTED_DATASETS: Mapping[str, DatasetDefinition] = MappingProxyType(_DATASETS)
DATASET_QUERY_ORDER = ("asos", "hrrr", "gfs", "mrms", "imerg_late")


@dataclass(frozen=True, slots=True)
class HistoricalWeatherRequest:
    """A report-day and city-envelope request with explicit UFOSINT uncertainty."""

    report_id: str
    report_day: date
    spatial_envelope: SpatialEnvelope
    coordinate_precision: Literal["city", "region", "approximate", "unknown"] = "city"
    day_uncertainty_days: int = 1
    source_key: str = "ufosint"
    event_time_basis: Literal["day_only"] = "day_only"
    scope_statement: str = field(default=NON_CAUSAL_SCOPE, init=False)

    def __post_init__(self) -> None:
        _identifier(self.report_id, label="report ID")
        _identifier(self.source_key, label="source key")
        if isinstance(self.report_day, datetime) or not isinstance(self.report_day, date):
            raise HistoricalWeatherError("report day must be a date without a time")
        if not 1 <= self.day_uncertainty_days <= 7:
            raise HistoricalWeatherError("day uncertainty must be within 1..7 days")

    @classmethod
    def from_ufosint_city(
        cls,
        *,
        report_id: str,
        report_day: date,
        latitude: float,
        longitude: float,
        city_uncertainty_km: float = 25.0,
        day_uncertainty_days: int = 1,
    ) -> HistoricalWeatherRequest:
        return cls(
            report_id=report_id,
            report_day=report_day,
            spatial_envelope=SpatialEnvelope.around_city(
                latitude=latitude,
                longitude=longitude,
                radius_km=city_uncertainty_km,
            ),
            coordinate_precision="city",
            day_uncertainty_days=day_uncertainty_days,
        )

    @property
    def temporal_envelope(self) -> TemporalEnvelope:
        start_day = self.report_day - timedelta(days=self.day_uncertainty_days)
        end_day = self.report_day + timedelta(days=self.day_uncertainty_days + 1)
        return TemporalEnvelope(_at_midnight(start_day), _at_midnight(end_day))

    @property
    def request_hash(self) -> str:
        return deterministic_hash(self.to_record())

    def to_record(self) -> dict[str, object]:
        return {
            "coordinate_precision": self.coordinate_precision,
            "day_uncertainty_days": self.day_uncertainty_days,
            "event_time_basis": self.event_time_basis,
            "report_day": self.report_day,
            "report_id": self.report_id,
            "scope_statement": self.scope_statement,
            "source_key": self.source_key,
            "spatial_envelope": self.spatial_envelope,
            "temporal_envelope": self.temporal_envelope,
        }


@dataclass(frozen=True, slots=True)
class DatasetQueryStep:
    rank: int
    dataset_key: str
    disposition: PlanDisposition
    availability_code: str
    reason: str
    temporal_envelope: TemporalEnvelope
    spatial_envelope: SpatialEnvelope
    variables: tuple[str, ...]
    source_dependencies: tuple[str, ...]
    limitations: tuple[str, ...]
    scope_statement: str = field(default=NON_CAUSAL_SCOPE, init=False)

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise HistoricalWeatherError("query rank must be positive")
        _identifier(self.dataset_key, label="query dataset key")
        _identifier(self.availability_code, label="availability code")
        _nonblank(self.reason, label="query reason")
        if not self.variables:
            raise HistoricalWeatherError("query step must request at least one variable")

    def to_record(self) -> dict[str, object]:
        return {
            "availability_code": self.availability_code,
            "dataset_key": self.dataset_key,
            "disposition": self.disposition,
            "limitations": self.limitations,
            "rank": self.rank,
            "reason": self.reason,
            "scope_statement": self.scope_statement,
            "source_dependencies": self.source_dependencies,
            "spatial_envelope": self.spatial_envelope,
            "temporal_envelope": self.temporal_envelope,
            "variables": self.variables,
        }


@dataclass(frozen=True, slots=True)
class HistoricalWeatherQueryPlan:
    request: HistoricalWeatherRequest
    steps: tuple[DatasetQueryStep, ...]
    schema_version: Literal[1] = 1
    scope_statement: str = field(default=NON_CAUSAL_SCOPE, init=False)

    def __post_init__(self) -> None:
        if tuple(step.rank for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise HistoricalWeatherError("query plan ranks must be contiguous")
        keys = tuple(step.dataset_key for step in self.steps)
        if len(keys) != len(set(keys)):
            raise HistoricalWeatherError("query plan dataset keys must be unique")

    @property
    def query_steps(self) -> tuple[DatasetQueryStep, ...]:
        return tuple(step for step in self.steps if step.disposition == "query")

    @property
    def unavailable_steps(self) -> tuple[DatasetQueryStep, ...]:
        return tuple(step for step in self.steps if step.disposition == "unavailable")

    @property
    def plan_hash(self) -> str:
        return deterministic_hash(self.to_record())

    def to_record(self) -> dict[str, object]:
        return {
            "request": self.request,
            "schema_version": self.schema_version,
            "scope_statement": self.scope_statement,
            "steps": self.steps,
        }


_PURPOSES = {
    "asos": (
        "Search station observations first because they are direct measurements, while "
        "retaining station distance, siting, missing-data, and upstream-feed caveats."
    ),
    "hrrr": (
        "Add high-resolution model-analysis context where the uncertain city envelope "
        "overlaps the HRRR domain."
    ),
    "gfs": (
        "Add global model-analysis context at a coarser scale when the report window "
        "overlaps the current GFS analysis archive."
    ),
    "mrms": (
        "Add CONUS radar/multisensor precipitation context while recording that MRMS "
        "shares radar, station, model, and climatology inputs."
    ),
    "imerg_late": (
        "Add global satellite precipitation context while retaining IMERG sensor, "
        "morphing, resolution, and era limitations."
    ),
}


def _availability(
    definition: DatasetDefinition,
    request: HistoricalWeatherRequest,
) -> tuple[PlanDisposition, str, str, tuple[str, ...]]:
    interval = request.temporal_envelope
    if interval.end_exclusive <= definition.temporal_start:
        return (
            "unavailable",
            "before_temporal_coverage",
            f"The uncertainty window ends before {definition.temporal_start.date().isoformat()}.",
            (),
        )
    if (
        definition.temporal_end_exclusive is not None
        and interval.start >= definition.temporal_end_exclusive
    ):
        return (
            "unavailable",
            "after_temporal_coverage",
            "The uncertainty window begins after this collection's temporal coverage.",
            (),
        )
    if not request.spatial_envelope.intersects(definition.coverage_envelope):
        return (
            "unavailable",
            "outside_spatial_coverage",
            f"The city envelope does not overlap {definition.coverage_label}.",
            (),
        )

    caveats: list[str] = []
    if interval.start < definition.temporal_start:
        caveats.append(
            "Only part of the uncertainty window overlaps the collection's temporal coverage."
        )
    if not request.spatial_envelope.is_within(definition.coverage_envelope):
        caveats.append(
            "Only part of the uncertainty envelope overlaps the collection's spatial coverage."
        )
    if definition.coverage_kind == "stations":
        caveats.append(
            "Catalog coverage does not guarantee a reporting station within the city envelope."
        )
    return "query", "eligible", _PURPOSES[definition.key], tuple(caveats)


def plan_historical_weather(
    request: HistoricalWeatherRequest,
    *,
    registry: Mapping[str, DatasetDefinition] = SUPPORTED_DATASETS,
) -> HistoricalWeatherQueryPlan:
    """Build a deterministic ASOS-first plan with explicit unavailable steps."""

    steps: list[DatasetQueryStep] = []
    for rank, key in enumerate(DATASET_QUERY_ORDER, start=1):
        try:
            definition = registry[key]
        except KeyError as exc:
            raise HistoricalWeatherError(f"dataset registry is missing {key!r}") from exc
        disposition, code, reason, planning_caveats = _availability(definition, request)
        steps.append(
            DatasetQueryStep(
                rank=rank,
                dataset_key=key,
                disposition=disposition,
                availability_code=code,
                reason=reason,
                temporal_envelope=request.temporal_envelope,
                spatial_envelope=request.spatial_envelope,
                variables=definition.variables,
                source_dependencies=definition.source_dependencies,
                limitations=(*definition.limitations, *planning_caveats),
            )
        )
    return HistoricalWeatherQueryPlan(request=request, steps=tuple(steps))


@dataclass(frozen=True, slots=True)
class WeatherEvidenceDatum:
    variable: str
    value: EvidenceValue
    unit: str | None
    valid_time: datetime
    latitude: float | None = None
    longitude: float | None = None
    station_id: str | None = None
    quality_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.variable, label="evidence variable")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise HistoricalWeatherError("evidence values must be finite")
        if self.unit is not None:
            _nonblank(self.unit, label="evidence unit")
        object.__setattr__(self, "valid_time", _utc(self.valid_time, label="evidence time"))
        if (self.latitude is None) != (self.longitude is None):
            raise HistoricalWeatherError(
                "evidence latitude and longitude must be supplied together"
            )
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise HistoricalWeatherError("evidence latitude is outside WGS84 bounds")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise HistoricalWeatherError("evidence longitude is outside WGS84 bounds")
        if self.station_id is not None:
            _identifier(self.station_id, label="station ID")

    def to_record(self) -> dict[str, object]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "quality_notes": self.quality_notes,
            "station_id": self.station_id,
            "unit": self.unit,
            "valid_time": self.valid_time,
            "value": self.value,
            "variable": self.variable,
        }


@dataclass(frozen=True, slots=True)
class AdapterPayload:
    """Validated, provider-neutral output from an explicitly supplied query function."""

    data: tuple[WeatherEvidenceDatum, ...]
    source_assets: tuple[str, ...]
    query_parameters: tuple[tuple[str, JsonScalar], ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.data:
            raise HistoricalWeatherError("adapter payload must contain evidence data")
        if not self.source_assets:
            raise HistoricalWeatherError("adapter payload must identify source assets")
        for asset in self.source_assets:
            if not asset.startswith("https://"):
                raise HistoricalWeatherError("source assets must use public HTTPS URLs")
        keys = tuple(key for key, _value in self.query_parameters)
        if len(keys) != len(set(keys)):
            raise HistoricalWeatherError("adapter query parameter keys must be unique")
        for key in keys:
            _nonblank(key, label="adapter query parameter key")


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    adapter_name: str
    adapter_version: str
    retrieved_at: datetime
    catalog_id: str
    stac_collection_id: str | None
    catalog_url: str
    stac_url: str | None
    source_assets: tuple[str, ...]
    query_parameters: tuple[tuple[str, JsonScalar], ...]
    license_id: str
    license_url: str | None
    attribution: str
    source_dependencies: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.adapter_name, label="adapter name")
        _nonblank(self.adapter_version, label="adapter version")
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, label="retrieval time"))

    def to_record(self) -> dict[str, object]:
        return {
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "attribution": self.attribution,
            "catalog_id": self.catalog_id,
            "catalog_url": self.catalog_url,
            "license_id": self.license_id,
            "license_url": self.license_url,
            "query_parameters": self.query_parameters,
            "retrieved_at": self.retrieved_at,
            "source_assets": self.source_assets,
            "source_dependencies": self.source_dependencies,
            "stac_collection_id": self.stac_collection_id,
            "stac_url": self.stac_url,
        }


@dataclass(frozen=True, slots=True)
class WeatherEvidenceArtifact:
    report_id: str
    request_hash: str
    plan_hash: str
    dataset_key: str
    status: ArtifactStatus
    availability_code: str
    provenance: EvidenceProvenance
    temporal_envelope: TemporalEnvelope
    spatial_envelope: SpatialEnvelope
    data: tuple[WeatherEvidenceDatum, ...]
    limitations: tuple[str, ...]
    failure_reason: str | None = None
    schema_version: Literal[1] = 1
    scope_statement: str = field(default=NON_CAUSAL_SCOPE, init=False)

    def __post_init__(self) -> None:
        _identifier(self.report_id, label="artifact report ID")
        _identifier(self.dataset_key, label="artifact dataset key")
        _identifier(self.availability_code, label="artifact availability code")
        for value, label in (
            (self.request_hash, "request hash"),
            (self.plan_hash, "plan hash"),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise HistoricalWeatherError(f"{label} must be a lowercase SHA-256 digest")
        if self.status == "available":
            if not self.data or not self.provenance.source_assets:
                raise HistoricalWeatherError(
                    "available artifacts require data and source assets"
                )
            if self.failure_reason is not None:
                raise HistoricalWeatherError("available artifacts cannot have a failure reason")
        else:
            if self.data:
                raise HistoricalWeatherError("unavailable artifacts must not expose partial data")
            if self.failure_reason is None:
                raise HistoricalWeatherError(
                    "unavailable artifacts require a bounded failure reason"
                )

    @property
    def artifact_hash(self) -> str:
        return deterministic_hash(self.to_record())

    def to_record(self) -> dict[str, object]:
        return {
            "availability_code": self.availability_code,
            "data": self.data,
            "dataset_key": self.dataset_key,
            "failure_reason": self.failure_reason,
            "limitations": self.limitations,
            "plan_hash": self.plan_hash,
            "provenance": self.provenance,
            "report_id": self.report_id,
            "request_hash": self.request_hash,
            "schema_version": self.schema_version,
            "scope_statement": self.scope_statement,
            "spatial_envelope": self.spatial_envelope,
            "status": self.status,
            "temporal_envelope": self.temporal_envelope,
        }


class WeatherQueryFunction(Protocol):
    def __call__(
        self,
        definition: DatasetDefinition,
        request: HistoricalWeatherRequest,
        step: DatasetQueryStep,
    ) -> AdapterPayload: ...


def _provenance(
    definition: DatasetDefinition,
    *,
    adapter_name: str,
    adapter_version: str,
    retrieved_at: datetime,
    payload: AdapterPayload | None,
) -> EvidenceProvenance:
    return EvidenceProvenance(
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        retrieved_at=retrieved_at,
        catalog_id=definition.catalog_id,
        stac_collection_id=definition.stac_collection_id,
        catalog_url=definition.catalog_url,
        stac_url=definition.stac_url,
        source_assets=() if payload is None else payload.source_assets,
        query_parameters=() if payload is None else payload.query_parameters,
        license_id=definition.license_id,
        license_url=definition.license_url,
        attribution=definition.attribution,
        source_dependencies=definition.source_dependencies,
    )


class OptionalWeatherQueryAdapter:
    """Opt-in adapter shell with no implicit imports or network access.

    Applications may inject a provider-specific query function after installing
    their preferred heavy dependencies.  Without that function, or if it raises,
    the adapter emits a provenance-bearing unavailable artifact and exposes no
    partial values.
    """

    def __init__(
        self,
        query_function: WeatherQueryFunction | None = None,
        *,
        name: str = "optional_weather_query",
        version: str = "1",
        registry: Mapping[str, DatasetDefinition] = SUPPORTED_DATASETS,
    ) -> None:
        self._query_function = query_function
        self._name = _identifier(name, label="adapter name")
        self._version = _nonblank(version, label="adapter version")
        self._registry = registry

    def query(
        self,
        plan: HistoricalWeatherQueryPlan,
        step: DatasetQueryStep,
        *,
        retrieved_at: datetime,
    ) -> WeatherEvidenceArtifact:
        retrieved = _utc(retrieved_at, label="adapter retrieval time")
        try:
            definition = self._registry[step.dataset_key]
        except KeyError as exc:
            raise HistoricalWeatherError(
                f"adapter registry does not contain {step.dataset_key!r}"
            ) from exc

        if step.disposition == "unavailable":
            return self._unavailable(
                plan,
                step,
                definition,
                retrieved,
                code=step.availability_code,
                reason=step.reason,
            )
        if self._query_function is None:
            return self._unavailable(
                plan,
                step,
                definition,
                retrieved,
                code="adapter_not_configured",
                reason=(
                    "No opt-in query function was supplied; no dependency was imported and "
                    "no network request was attempted."
                ),
            )

        try:
            payload = self._query_function(definition, plan.request, step)
            if not isinstance(payload, AdapterPayload):
                raise HistoricalWeatherError("query function returned an invalid payload type")
        except Exception as exc:  # fail closed at the external data boundary
            return self._unavailable(
                plan,
                step,
                definition,
                retrieved,
                code="adapter_failure",
                reason=(
                    "The optional query failed closed without exposing partial data "
                    f"({type(exc).__name__})."
                ),
            )

        return WeatherEvidenceArtifact(
            report_id=plan.request.report_id,
            request_hash=plan.request.request_hash,
            plan_hash=plan.plan_hash,
            dataset_key=definition.key,
            status="available",
            availability_code="available",
            provenance=_provenance(
                definition,
                adapter_name=self._name,
                adapter_version=self._version,
                retrieved_at=retrieved,
                payload=payload,
            ),
            temporal_envelope=step.temporal_envelope,
            spatial_envelope=step.spatial_envelope,
            data=payload.data,
            limitations=(*step.limitations, *payload.limitations),
        )

    def _unavailable(
        self,
        plan: HistoricalWeatherQueryPlan,
        step: DatasetQueryStep,
        definition: DatasetDefinition,
        retrieved_at: datetime,
        *,
        code: str,
        reason: str,
    ) -> WeatherEvidenceArtifact:
        return WeatherEvidenceArtifact(
            report_id=plan.request.report_id,
            request_hash=plan.request.request_hash,
            plan_hash=plan.plan_hash,
            dataset_key=definition.key,
            status="unavailable",
            availability_code=code,
            provenance=_provenance(
                definition,
                adapter_name=self._name,
                adapter_version=self._version,
                retrieved_at=retrieved_at,
                payload=None,
            ),
            temporal_envelope=step.temporal_envelope,
            spatial_envelope=step.spatial_envelope,
            data=(),
            limitations=step.limitations,
            failure_reason=_nonblank(reason, label="failure reason")[:500],
        )


__all__ = [
    "AdapterPayload",
    "CATALOG_ROOT_URL",
    "DATASET_QUERY_ORDER",
    "DatasetDefinition",
    "DatasetQueryStep",
    "EvidenceProvenance",
    "GLOBAL_ENVELOPE",
    "HistoricalWeatherError",
    "HistoricalWeatherQueryPlan",
    "HistoricalWeatherRequest",
    "NON_CAUSAL_SCOPE",
    "OptionalWeatherQueryAdapter",
    "SUPPORTED_DATASETS",
    "SpatialEnvelope",
    "TemporalEnvelope",
    "WeatherEvidenceArtifact",
    "WeatherEvidenceDatum",
    "canonical_json_bytes",
    "deterministic_hash",
    "plan_historical_weather",
]
