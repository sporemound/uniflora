from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from uniflora.dynamical_context import (
    NON_CAUSAL_SCOPE,
    SUPPORTED_DATASETS,
    AdapterPayload,
    HistoricalWeatherError,
    HistoricalWeatherRequest,
    OptionalWeatherQueryAdapter,
    SpatialEnvelope,
    WeatherEvidenceDatum,
    canonical_json_bytes,
    deterministic_hash,
    plan_historical_weather,
)


def _request(
    *,
    report_day: date = date(2024, 4, 8),
    latitude: float = 34.05,
    longitude: float = -118.25,
) -> HistoricalWeatherRequest:
    return HistoricalWeatherRequest.from_ufosint_city(
        report_id="ufosint:618999",
        report_day=report_day,
        latitude=latitude,
        longitude=longitude,
    )


def _step(plan, key: str):
    return next(step for step in plan.steps if step.dataset_key == key)


def test_registry_contains_authoritative_catalog_and_stac_ids() -> None:
    assert tuple(SUPPORTED_DATASETS) == (
        "asos",
        "hrrr",
        "gfs",
        "mrms",
        "imerg_late",
    )
    assert SUPPORTED_DATASETS["asos"].catalog_id == "asos-parquet"
    assert SUPPORTED_DATASETS["asos"].stac_collection_id is None
    assert SUPPORTED_DATASETS["gfs"].stac_collection_id == "noaa-gfs-analysis"
    assert SUPPORTED_DATASETS["hrrr"].stac_collection_id == "noaa-hrrr-analysis"
    assert (
        SUPPORTED_DATASETS["mrms"].stac_collection_id
        == "noaa-mrms-conus-analysis-hourly"
    )
    assert (
        SUPPORTED_DATASETS["imerg_late"].stac_collection_id
        == "nasa-imerg-analysis-late"
    )


def test_registry_captures_coverage_variables_and_license_caveat() -> None:
    assert SUPPORTED_DATASETS["gfs"].temporal_start == datetime(
        2021, 5, 1, tzinfo=UTC
    )
    assert SUPPORTED_DATASETS["hrrr"].spatial_resolution == "3 km"
    assert "precipitation_surface" in SUPPORTED_DATASETS["mrms"].variables
    assert SUPPORTED_DATASETS["imerg_late"].variables == (
        "precipitation_quality_index_surface",
        "precipitation_surface",
    )
    assert SUPPORTED_DATASETS["imerg_late"].license_id == "CC-BY-4.0"
    assert SUPPORTED_DATASETS["asos"].license_id == (
        "not-stated-on-dynamical-catalog-page"
    )
    assert any(
        "verify" in limitation.casefold()
        for limitation in SUPPORTED_DATASETS["asos"].limitations
    )


def test_registry_and_definitions_are_immutable() -> None:
    with pytest.raises(TypeError):
        SUPPORTED_DATASETS["invented"] = SUPPORTED_DATASETS["asos"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        SUPPORTED_DATASETS["gfs"].title = "changed"  # type: ignore[misc]


def test_ufosint_request_expands_day_and_city_uncertainty() -> None:
    request = _request()

    assert request.coordinate_precision == "city"
    assert request.event_time_basis == "day_only"
    assert request.temporal_envelope.start == datetime(2024, 4, 7, tzinfo=UTC)
    assert request.temporal_envelope.end_exclusive == datetime(2024, 4, 10, tzinfo=UTC)
    assert request.spatial_envelope.west < -118.25 < request.spatial_envelope.east
    assert request.spatial_envelope.south < 34.05 < request.spatial_envelope.north
    assert request.scope_statement == NON_CAUSAL_SCOPE


def test_request_rejects_false_exactness() -> None:
    with pytest.raises(HistoricalWeatherError, match="day uncertainty"):
        HistoricalWeatherRequest(
            report_id="ufosint:1",
            report_day=date(2024, 1, 1),
            spatial_envelope=SpatialEnvelope.around_city(
                latitude=40,
                longitude=-90,
            ),
            day_uncertainty_days=0,
        )

    with pytest.raises(HistoricalWeatherError, match="radius"):
        SpatialEnvelope.around_city(latitude=40, longitude=-90, radius_km=0)


def test_request_and_plan_hashes_are_canonical_and_deterministic() -> None:
    first = _request()
    second = _request()
    first_plan = plan_historical_weather(first)
    second_plan = plan_historical_weather(second)

    assert first.request_hash == second.request_hash
    assert first_plan.plan_hash == second_plan.plan_hash
    assert canonical_json_bytes({"z": 1, "a": 2}) == b'{"a":2,"z":1}'
    assert deterministic_hash({"a": 2, "z": 1}) == deterministic_hash(
        {"z": 1, "a": 2}
    )
    with pytest.raises(HistoricalWeatherError, match="non-finite"):
        canonical_json_bytes({"bad": float("nan")})


def test_conus_current_plan_is_asos_first_and_retains_all_dependencies() -> None:
    plan = plan_historical_weather(_request())

    assert tuple(step.dataset_key for step in plan.query_steps) == (
        "asos",
        "hrrr",
        "gfs",
        "mrms",
        "imerg_late",
    )
    assert all(step.disposition == "query" for step in plan.steps)
    assert any("radar assimilation" in item for item in _step(plan, "hrrr").source_dependencies)
    assert any("not independent" in item for item in _step(plan, "mrms").source_dependencies)
    assert all(step.scope_statement == NON_CAUSAL_SCOPE for step in plan.steps)


def test_older_global_plan_records_unavailable_sources_instead_of_dropping_them() -> None:
    plan = plan_historical_weather(
        _request(
            report_day=date(2005, 6, 1),
            latitude=-33.87,
            longitude=151.21,
        )
    )

    assert tuple(step.dataset_key for step in plan.query_steps) == ("asos", "imerg_late")
    assert _step(plan, "hrrr").availability_code == "before_temporal_coverage"
    assert _step(plan, "gfs").availability_code == "before_temporal_coverage"
    assert _step(plan, "mrms").availability_code == "before_temporal_coverage"
    assert {step.dataset_key for step in plan.unavailable_steps} == {"hrrr", "gfs", "mrms"}


def test_pre_imerg_request_queries_only_asos() -> None:
    plan = plan_historical_weather(
        _request(report_day=date(1985, 1, 1), latitude=51.5, longitude=-0.12)
    )

    assert tuple(step.dataset_key for step in plan.query_steps) == ("asos",)
    assert all(
        step.availability_code == "before_temporal_coverage"
        for step in plan.unavailable_steps
    )


def test_partial_temporal_overlap_remains_queryable_with_explicit_caveat() -> None:
    plan = plan_historical_weather(_request(report_day=date(2021, 4, 30)))
    gfs = _step(plan, "gfs")

    assert gfs.disposition == "query"
    assert any("Only part" in limitation for limitation in gfs.limitations)


def test_optional_adapter_attempts_no_query_when_not_configured() -> None:
    plan = plan_historical_weather(_request())
    artifact = OptionalWeatherQueryAdapter().query(
        plan,
        _step(plan, "asos"),
        retrieved_at=datetime(2024, 4, 11, tzinfo=UTC),
    )

    assert artifact.status == "unavailable"
    assert artifact.availability_code == "adapter_not_configured"
    assert artifact.data == ()
    assert artifact.provenance.source_assets == ()
    assert "no network request" in (artifact.failure_reason or "")


def test_optional_adapter_does_not_call_provider_for_unavailable_step() -> None:
    calls = 0

    def query(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("unavailable steps must not call an external provider")

    plan = plan_historical_weather(
        _request(report_day=date(1985, 1, 1), latitude=51.5, longitude=-0.12)
    )
    artifact = OptionalWeatherQueryAdapter(query).query(
        plan,
        _step(plan, "gfs"),
        retrieved_at=datetime(2024, 4, 11, tzinfo=UTC),
    )

    assert calls == 0
    assert artifact.status == "unavailable"
    assert artifact.availability_code == "before_temporal_coverage"


def test_optional_adapter_fails_closed_without_partial_data() -> None:
    def query(*_args):
        raise OSError("secret-bearing provider failure")

    plan = plan_historical_weather(_request())
    artifact = OptionalWeatherQueryAdapter(query).query(
        plan,
        _step(plan, "gfs"),
        retrieved_at=datetime(2024, 4, 11, tzinfo=UTC),
    )

    assert artifact.status == "unavailable"
    assert artifact.availability_code == "adapter_failure"
    assert artifact.data == ()
    assert "OSError" in (artifact.failure_reason or "")
    assert "secret-bearing" not in (artifact.failure_reason or "")


def test_injected_adapter_creates_provenance_rich_stable_artifact() -> None:
    retrieved_at = datetime(2024, 4, 11, 12, tzinfo=UTC)

    def query(definition, request, step):
        assert definition.key == "gfs"
        assert request.event_time_basis == "day_only"
        assert step.spatial_envelope == request.spatial_envelope
        return AdapterPayload(
            data=(
                WeatherEvidenceDatum(
                    variable="total_cloud_cover_atmosphere",
                    value=75.0,
                    unit="percent",
                    valid_time=datetime(2024, 4, 8, 18, tzinfo=UTC),
                    latitude=34.0,
                    longitude=-118.25,
                    quality_notes=("Nearest grid cell in the requested envelope.",),
                ),
            ),
            source_assets=(definition.stac_url or "",),
            query_parameters=(
                ("selection", "nearest"),
                ("time_basis", "day_uncertain"),
            ),
            limitations=("One model grid sample does not represent a causal test.",),
        )

    plan = plan_historical_weather(_request())
    adapter = OptionalWeatherQueryAdapter(query, name="fixture_adapter", version="1.2.3")
    first = adapter.query(plan, _step(plan, "gfs"), retrieved_at=retrieved_at)
    second = adapter.query(plan, _step(plan, "gfs"), retrieved_at=retrieved_at)

    assert first.status == "available"
    assert first.artifact_hash == second.artifact_hash
    assert first.request_hash == plan.request.request_hash
    assert first.plan_hash == plan.plan_hash
    assert first.provenance.catalog_id == "noaa-gfs-analysis"
    assert first.provenance.stac_collection_id == "noaa-gfs-analysis"
    assert first.provenance.license_id == "CC-BY-4.0"
    assert first.provenance.source_dependencies
    assert first.scope_statement == NON_CAUSAL_SCOPE
    assert b'"scope_statement"' in canonical_json_bytes(first)


def test_available_artifact_and_data_are_immutable() -> None:
    datum = WeatherEvidenceDatum(
        variable="temperature_2m",
        value=12.5,
        unit="degree_Celsius",
        valid_time=datetime(2024, 4, 8, 12, tzinfo=UTC),
    )

    with pytest.raises(FrozenInstanceError):
        datum.value = 99  # type: ignore[misc]
