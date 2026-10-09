from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime

import pytest

from uniflora.dynamical_context import (
    AdapterPayload,
    OptionalWeatherQueryAdapter,
    WeatherEvidenceDatum,
    canonical_json_bytes,
    plan_historical_weather,
)
from uniflora.ufosint_sidequest_sync import (
    ActivityArtifactProjection,
    SidequestHttpResponse,
    SidequestSyncError,
    UfosintSidequestAnalysisWorker,
    UfosintSidequestSyncClient,
    parse_job_response,
    project_dynamical_analysis,
)


@dataclass(frozen=True, slots=True)
class _Call:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes


class _Transport:
    def __init__(
        self,
        responder: Callable[[_Call], SidequestHttpResponse],
    ) -> None:
        self.calls: list[_Call] = []
        self._responder = responder

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> SidequestHttpResponse:
        call = _Call(method=method, url=url, headers=dict(headers), body=body)
        self.calls.append(call)
        return self._responder(call)


def _json_response(payload: object, *, status: int = 200) -> SidequestHttpResponse:
    return SidequestHttpResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(),
    )


def _report_snapshot() -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0",
        "sourceKey": "ufosint",
        "reportId": "ufosint:1001",
        "sourceName": "UFOSINT",
        "sourcePageUrl": "https://ufosint.com/reports",
        "sourceUrl": "https://ufosint.com/report/test_001",
        "observedAt": "2025-06-14T00:00:00.000Z",
        "indexedAt": "2025-06-14T01:00:00.000Z",
        "latitude": 34.05,
        "longitude": -118.25,
        "title": "Unverified city-scale report",
        "locationName": "Los Angeles, California",
        "coordinatePrecision": "city",
        "summary": "A public, privacy-reduced report awaiting independent review.",
        "status": "unverified",
        "qualityScore": 72,
    }


def _job_record(
    *,
    revision: int = 4,
    completed_dataset_keys: tuple[str, ...] = (),
    required_dataset_keys: tuple[str, ...] = (
        "asos",
        "hrrr",
        "gfs",
        "mrms",
        "imerg_late",
    ),
) -> dict[str, object]:
    report = _report_snapshot()
    return {
        "sidequestId": "sidequest:weather:001",
        "revision": revision,
        "completedDatasetKeys": list(completed_dataset_keys),
        "requiredDatasetKeys": list(required_dataset_keys),
        "reportSnapshotSha256": hashlib.sha256(canonical_json_bytes(report)).hexdigest(),
        "reportSnapshot": report,
        "timeUncertainty": {
            "basis": "day_only",
            "reportDay": "2025-06-14",
            "dayUncertaintyDays": 1,
        },
    }


def _job_response(
    *,
    revision: int = 4,
    completed_dataset_keys: tuple[str, ...] = (),
    required_dataset_keys: tuple[str, ...] = (
        "asos",
        "hrrr",
        "gfs",
        "mrms",
        "imerg_late",
    ),
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0",
        "jobs": [
            _job_record(
                revision=revision,
                completed_dataset_keys=completed_dataset_keys,
                required_dataset_keys=required_dataset_keys,
            )
        ],
    }


def _job():
    return parse_job_response(_job_response()).jobs[0]


def _available_projection() -> ActivityArtifactProjection:
    job = _job()
    plan = plan_historical_weather(job.historical_weather_request())
    step = plan.query_steps[0]

    def query(*_args: object) -> AdapterPayload:
        return AdapterPayload(
            data=(
                WeatherEvidenceDatum(
                    variable="air_temperature",
                    value=18.5,
                    unit="degree_Celsius",
                    valid_time=datetime(2025, 6, 14, 12, tzinfo=UTC),
                    latitude=34.05,
                    longitude=-118.25,
                    station_id="KLAX",
                    quality_notes=("Illustrative injected test observation.",),
                ),
            ),
            source_assets=("https://example.test/asos/KLAX/2025-06-14.json",),
            query_parameters=(("station", "KLAX"),),
            limitations=("The station is not the exact witness location.",),
        )

    adapter = OptionalWeatherQueryAdapter(
        query,
        name="test_weather_adapter",
        version="2026.08",
    )
    evidence = adapter.query(
        plan,
        step,
        retrieved_at=datetime(2026, 8, 2, 16, 30, tzinfo=UTC),
    )
    return project_dynamical_analysis(job, evidence)


def _available_adapter(
    dataset_key: str,
    queried: list[str],
) -> OptionalWeatherQueryAdapter:
    def query(definition, _request, _step) -> AdapterPayload:  # type: ignore[no-untyped-def]
        assert definition.key == dataset_key
        queried.append(dataset_key)
        return AdapterPayload(
            data=(
                WeatherEvidenceDatum(
                    variable="context_value",
                    value=1.0,
                    unit="test_unit",
                    valid_time=datetime(2025, 6, 14, 6, tzinfo=UTC),
                ),
            ),
            source_assets=(f"https://example.test/{dataset_key}/context.json",),
        )

    return OptionalWeatherQueryAdapter(
        query,
        name=f"injected_{dataset_key}",
        version="1",
    )


def _client(
    transport: _Transport,
    *,
    nonce_factory: Callable[[], str] = lambda: "nonce:sidequest:0001",
) -> UfosintSidequestSyncClient:
    return UfosintSidequestSyncClient(
        "https://activity.example.test",
        "test-secret",
        transport=transport,
        clock=lambda: 1_754_000_000,
        nonce_factory=nonce_factory,
    )


def test_list_jobs_signs_empty_body_and_excludes_query_from_canonical_path() -> None:
    transport = _Transport(
        lambda _call: _json_response({"schemaVersion": "1.0.0", "jobs": []})
    )

    batch = _client(transport).list_jobs(limit=17)

    assert batch.jobs == ()
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert request.method == "GET"
    assert request.url == (
        "https://activity.example.test/api/hypha/ufosint-sidequests/jobs?limit=17"
    )
    assert request.body == b""
    content_sha256 = hashlib.sha256(b"").hexdigest()
    canonical = "\n".join(
        (
            "GET",
            "/api/hypha/ufosint-sidequests/jobs",
            "1754000000",
            "nonce:sidequest:0001",
            content_sha256,
        )
    )
    signature = hmac.new(
        b"test-secret",
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert request.headers["X-Hypha-Content-SHA256"] == content_sha256
    assert request.headers["X-Hypha-Signature"] == f"v1={signature}"
    assert "Content-Type" not in request.headers


def test_job_parser_pins_snapshot_and_preserves_date_only_uncertainty() -> None:
    job = _job()

    assert job.report_snapshot.report_id == "ufosint:1001"
    assert job.report_snapshot_sha256 == hashlib.sha256(
        canonical_json_bytes(_report_snapshot())
    ).hexdigest()
    assert job.time_uncertainty.basis == "day_only"
    assert job.time_uncertainty.report_day.isoformat() == "2025-06-14"
    assert job.completed_dataset_keys == ()
    assert job.required_dataset_keys == (
        "asos",
        "hrrr",
        "gfs",
        "mrms",
        "imerg_late",
    )
    request = job.historical_weather_request()
    assert request.event_time_basis == "day_only"
    assert request.day_uncertainty_days == 1
    assert request.temporal_envelope.start.isoformat() == "2025-06-13T00:00:00+00:00"
    assert request.temporal_envelope.end_exclusive.isoformat() == (
        "2025-06-16T00:00:00+00:00"
    )
    assert request.spatial_envelope.north == pytest.approx(34.05 + 50.0 / 111.32)
    with pytest.raises(FrozenInstanceError):
        job.revision = 9  # type: ignore[misc]


def test_job_parser_rejects_hash_shape_and_uncertainty_mismatches() -> None:
    bad_hash = _job_response()
    bad_hash_job = bad_hash["jobs"][0]  # type: ignore[index]
    bad_hash_job["reportSnapshotSha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(SidequestSyncError, match="immutable content hash"):
        parse_job_response(bad_hash)

    extra_field = _job_response()
    extra_job = extra_field["jobs"][0]  # type: ignore[index]
    extra_job["analysisPlan"] = {}  # type: ignore[index]
    with pytest.raises(SidequestSyncError, match="unexpected analysisPlan"):
        parse_job_response(extra_field)

    wrong_day = _job_response()
    wrong_day_job = wrong_day["jobs"][0]  # type: ignore[index]
    wrong_day_job["timeUncertainty"]["reportDay"] = "2025-06-15"  # type: ignore[index]
    with pytest.raises(SidequestSyncError, match="does not match"):
        parse_job_response(wrong_day)


def test_job_parser_rejects_non_quantized_report_coordinates() -> None:
    payload = _job_response()
    job = payload["jobs"][0]  # type: ignore[index]
    report = job["reportSnapshot"]  # type: ignore[index]
    report["latitude"] = 34.051  # type: ignore[index]
    job["reportSnapshotSha256"] = hashlib.sha256(  # type: ignore[index]
        canonical_json_bytes(report)
    ).hexdigest()

    with pytest.raises(SidequestSyncError, match="0.05-degree grid"):
        parse_job_response(payload)


def test_job_parser_rejects_invalid_dataset_progress_contract() -> None:
    unsupported = _job_response()
    unsupported_job = unsupported["jobs"][0]  # type: ignore[index]
    unsupported_job["requiredDatasetKeys"] = ["asos", "unknown"]  # type: ignore[index]
    with pytest.raises(SidequestSyncError, match="unsupported Dynamical dataset key"):
        parse_job_response(unsupported)

    not_a_subset = _job_response(
        completed_dataset_keys=("gfs",),
        required_dataset_keys=("asos",),
    )
    with pytest.raises(SidequestSyncError, match="must be a subset"):
        parse_job_response(not_a_subset)


def test_projection_matches_shared_dynamical_artifact_metadata_contract() -> None:
    projection = _available_projection()
    metadata = projection.to_record()

    assert set(metadata) == {
        "artifactId",
        "kind",
        "title",
        "mediaType",
        "contentSha256",
        "byteLength",
        "artifactUri",
        "dynamicalAnalysis",
        "provenance",
    }
    assert metadata["kind"] == "dynamical_analysis"
    assert metadata["artifactId"] == projection.artifact_id
    assert metadata["contentSha256"] == hashlib.sha256(projection.content).hexdigest()
    assert metadata["byteLength"] == len(projection.content)
    assert metadata["artifactUri"] is None

    analysis = metadata["dynamicalAnalysis"]
    assert set(analysis) == {  # type: ignore[arg-type]
        "modelId",
        "modelVersion",
        "implementation",
        "coordinateFrame",
        "timeStandard",
        "timeWindowStart",
        "timeWindowEnd",
        "initialConditions",
        "parameters",
        "derivedValues",
        "assumptions",
        "uncertaintyStatements",
        "limitations",
        "softwareVersions",
    }
    uncertainty = analysis["uncertaintyStatements"]  # type: ignore[index]
    assert any("not an authoritative event time" in item for item in uncertainty)
    assert any("Privacy-reduced city coordinate" in item for item in uncertainty)
    assert analysis["limitations"]  # type: ignore[index]
    assert analysis["softwareVersions"]  # type: ignore[index]

    provenance = metadata["provenance"]
    report_parent = provenance[0]  # type: ignore[index]
    assert report_parent["parentType"] == "report_snapshot"
    assert report_parent["parentReference"] == "ufosint:1001"
    assert report_parent["parentContentSha256"] == _job().report_snapshot_sha256
    assert report_parent["relation"] == "derived_from"
    assert all(
        item["relation"] == "contextualizes" and item["parentContentSha256"] is None
        for item in provenance[1:]  # type: ignore[index]
    )


def test_projection_rejects_unavailable_adapter_artifact() -> None:
    job = _job()
    plan = plan_historical_weather(job.historical_weather_request())
    unavailable = OptionalWeatherQueryAdapter().query(
        plan,
        plan.query_steps[0],
        retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    with pytest.raises(SidequestSyncError, match="Unavailable evidence"):
        project_dynamical_analysis(job, unavailable)


def test_attach_posts_exact_canonical_body_and_path_signature() -> None:
    projection = _available_projection()
    job = _job()
    receipt_payload = {
        "ok": True,
        "sidequestId": job.sidequest_id,
        "revision": job.revision + 1,
        "artifactId": projection.artifact_id,
    }
    transport = _Transport(lambda _call: _json_response(receipt_payload, status=201))

    receipt = _client(transport).attach_artifact(job, projection)

    assert receipt.artifact_id == projection.artifact_id
    request = transport.calls[0]
    path = "/api/hypha/ufosint-sidequests/sidequest:weather:001/artifacts"
    assert request.method == "POST"
    assert request.url == f"https://activity.example.test{path}"
    payload = json.loads(request.body)
    assert set(payload) == {
        "operationId",
        "expectedRevision",
        "artifact",
        "contentBase64",
    }
    assert payload["operationId"] == f"attach:{projection.artifact_id}"
    assert payload["expectedRevision"] == 4
    assert payload["artifact"] == projection.to_record()
    assert base64.b64decode(payload["contentBase64"], validate=True) == projection.content
    assert request.body == canonical_json_bytes(payload)

    content_sha256 = hashlib.sha256(request.body).hexdigest()
    canonical = "\n".join(
        (
            "POST",
            path,
            "1754000000",
            "nonce:sidequest:0001",
            content_sha256,
        )
    )
    expected = hmac.new(b"test-secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert request.headers["X-Hypha-Signature"] == f"v1={expected}"
    assert request.headers["Content-Type"] == "application/json"


def test_attach_rejects_content_that_does_not_match_metadata_before_transport() -> None:
    projection = _available_projection()
    tampered = ActivityArtifactProjection(
        artifact_id=projection.artifact_id,
        content_sha256=projection.content_sha256,
        content=projection.content + b"tampered",
        metadata_json=projection.metadata_json,
    )
    transport = _Transport(
        lambda _call: pytest.fail("inconsistent artifact must not reach transport")
    )

    with pytest.raises(SidequestSyncError, match="does not match its content bytes"):
        _client(transport).attach_artifact(_job(), tampered)

    assert transport.calls == []


def test_one_cycle_uploads_first_available_explicit_adapter_result() -> None:
    nonces = iter(("nonce:sidequest:list01", "nonce:sidequest:post01"))

    def respond(call: _Call) -> SidequestHttpResponse:
        if call.method == "GET":
            return _json_response(_job_response())
        payload = json.loads(call.body)
        return _json_response(
            {
                "ok": True,
                "sidequestId": "sidequest:weather:001",
                "revision": 5,
                "artifactId": payload["artifact"]["artifactId"],
            },
            status=201,
        )

    queried: list[str] = []

    def query(definition, _request, _step) -> AdapterPayload:  # type: ignore[no-untyped-def]
        queried.append(definition.key)
        return AdapterPayload(
            data=(
                WeatherEvidenceDatum(
                    variable="wind_speed",
                    value=4.2,
                    unit="m/s",
                    valid_time=datetime(2025, 6, 14, 6, tzinfo=UTC),
                    station_id="KLAX",
                ),
            ),
            source_assets=("https://example.test/asos/KLAX.json",),
        )

    transport = _Transport(respond)
    worker = UfosintSidequestAnalysisWorker(
        _client(transport, nonce_factory=lambda: next(nonces)),
        adapters={
            "asos": OptionalWeatherQueryAdapter(
                query,
                name="injected_asos",
                version="1",
            )
        },
        clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )

    cycle = worker.run_cycle(limit=3)

    assert cycle.jobs_received == 1
    assert cycle.uploaded_count == 1
    assert cycle.outcomes[0].status == "uploaded"
    assert cycle.outcomes[0].dataset_key == "asos"
    assert cycle.outcomes[0].revision == 5
    assert queried == ["asos"]
    assert [call.method for call in transport.calls] == ["GET", "POST"]


def test_one_cycle_uploads_every_available_required_dataset_in_revision_order() -> None:
    nonces = iter(
        (
            "nonce:progress:list01",
            "nonce:progress:post01",
            "nonce:progress:post02",
            "nonce:progress:post03",
        )
    )
    next_revision = 4

    def respond(call: _Call) -> SidequestHttpResponse:
        nonlocal next_revision
        if call.method == "GET":
            return _json_response(
                _job_response(required_dataset_keys=("asos", "hrrr", "gfs"))
            )
        payload = json.loads(call.body)
        assert payload["expectedRevision"] == next_revision
        next_revision += 1
        return _json_response(
            {
                "ok": True,
                "sidequestId": "sidequest:weather:001",
                "revision": next_revision,
                "artifactId": payload["artifact"]["artifactId"],
            },
            status=201,
        )

    queried: list[str] = []
    transport = _Transport(respond)
    worker = UfosintSidequestAnalysisWorker(
        _client(transport, nonce_factory=lambda: next(nonces)),
        adapters={
            key: _available_adapter(key, queried) for key in ("asos", "hrrr", "gfs")
        },
        clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )

    cycle = worker.run_cycle()

    outcome = cycle.outcomes[0]
    assert outcome.status == "uploaded"
    assert outcome.uploaded_dataset_keys == ("asos", "hrrr", "gfs")
    assert len(outcome.artifact_ids) == 3
    assert outcome.completed_dataset_keys == ("asos", "hrrr", "gfs")
    assert outcome.pending_dataset_keys == ()
    assert outcome.revision == 7
    assert cycle.artifact_upload_count == 3
    assert queried == ["asos", "hrrr", "gfs"]
    assert [call.method for call in transport.calls] == ["GET", "POST", "POST", "POST"]
    expected_revisions = [
        json.loads(call.body)["expectedRevision"]
        for call in transport.calls
        if call.method == "POST"
    ]
    assert expected_revisions == [4, 5, 6]


def test_partial_upload_retries_only_uncompleted_dataset_with_latest_revision() -> None:
    nonces = iter(
        (
            "nonce:retry:list0001",
            "nonce:retry:post0001",
            "nonce:retry:post0002",
            "nonce:retry:list0002",
            "nonce:retry:post0003",
        )
    )
    get_count = 0
    post_count = 0

    def respond(call: _Call) -> SidequestHttpResponse:
        nonlocal get_count, post_count
        if call.method == "GET":
            get_count += 1
            if get_count == 1:
                return _json_response(
                    _job_response(required_dataset_keys=("asos", "hrrr"))
                )
            return _json_response(
                _job_response(
                    revision=5,
                    completed_dataset_keys=("asos",),
                    required_dataset_keys=("asos", "hrrr"),
                )
            )
        post_count += 1
        payload = json.loads(call.body)
        if post_count == 2:
            return _json_response({"error": "temporary failure"}, status=503)
        return _json_response(
            {
                "ok": True,
                "sidequestId": "sidequest:weather:001",
                "revision": payload["expectedRevision"] + 1,
                "artifactId": payload["artifact"]["artifactId"],
            },
            status=201,
        )

    queried: list[str] = []
    transport = _Transport(respond)
    worker = UfosintSidequestAnalysisWorker(
        _client(transport, nonce_factory=lambda: next(nonces)),
        adapters={
            key: _available_adapter(key, queried) for key in ("asos", "hrrr", "gfs")
        },
        clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )

    first = worker.run_cycle()
    second = worker.run_cycle()

    first_outcome = first.outcomes[0]
    assert first_outcome.status == "partial"
    assert first_outcome.uploaded_dataset_keys == ("asos",)
    assert first_outcome.completed_dataset_keys == ("asos",)
    assert first_outcome.pending_dataset_keys == ("hrrr",)
    assert first_outcome.revision == 5
    assert first.artifact_upload_count == 1

    second_outcome = second.outcomes[0]
    assert second_outcome.status == "uploaded"
    assert second_outcome.attempted_dataset_keys == ("hrrr",)
    assert second_outcome.uploaded_dataset_keys == ("hrrr",)
    assert second_outcome.completed_dataset_keys == ("asos", "hrrr")
    assert second_outcome.pending_dataset_keys == ()
    assert second_outcome.revision == 6
    assert queried == ["asos", "hrrr", "hrrr"]

    post_payloads = [
        json.loads(call.body) for call in transport.calls if call.method == "POST"
    ]
    assert [payload["expectedRevision"] for payload in post_payloads] == [4, 5, 5]
    assert post_payloads[1]["operationId"] == post_payloads[2]["operationId"]


def test_one_cycle_fails_closed_without_adapter_data_and_does_not_post() -> None:
    transport = _Transport(lambda _call: _json_response(_job_response()))
    worker = UfosintSidequestAnalysisWorker(
        _client(transport),
        adapters={"asos": OptionalWeatherQueryAdapter()},
        clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
    )

    cycle = worker.run_cycle()

    assert cycle.uploaded_count == 0
    assert cycle.outcomes[0].status == "unavailable"
    assert cycle.outcomes[0].attempted_dataset_keys == ("asos",)
    assert "adapter_not_configured" in (cycle.outcomes[0].reason or "")
    assert [call.method for call in transport.calls] == ["GET"]
