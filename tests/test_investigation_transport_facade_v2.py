from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2AnalysisJob,
    V2AnalysisMethod,
    V2AnalysisPresentationService,
    V2AnalysisTextCommandAdapter,
    V2AnalysisTransportResponse,
    V2PersistentInvestigationService,
    V2SQLiteAnalysisStore,
    V2SQLiteEventStore,
    V2TextCommandAdapter,
    V2TransportFacade,
    V2TransportResponse,
    calculate_dataset_hash,
    classify_transport_command,
    create_analysis_job_envelope,
)
from uniflora.engine.v2.analysis import V2AnalysisInput

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _job_envelope():
    retained = b"retained-observation"
    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id="job_clock_alignment",
            stream_id="session",
            position_id="boundary_event",
            requested_by_player_id="player_a",
            method=V2AnalysisMethod(
                method_id="cross_source_clock_alignment",
                version="1.0.0",
                implementation=(
                    "uniflora.engine.v2.analysis_methods:execute_cross_source_clock_alignment"
                ),
                description="Estimate a constant cross-source clock offset.",
            ),
            inputs=(
                V2AnalysisInput(
                    dataset_id="boundary_optical",
                    source_evidence_id="optical_record",
                    content_hash=calculate_dataset_hash(retained),
                    byte_length=len(retained),
                    media_type="application/octet-stream",
                    provenance="Retained fixture bytes.",
                ),
            ),
            parameters=(),
            output_kind="cross_source_clock_alignment_report",
        )
    )


@pytest.mark.parametrize(
    ("text", "route"),
    [
        ("assign-role instrument_operator", "investigation"),
        ("/analysis-status job_1", "analysis"),
        ("v2 analysis_artifact artifact_1", "analysis"),
        ('analysis-status "unterminated', "analysis"),
        ("analysis-unknown value", "analysis"),
        ("v2", "investigation"),
        ("", "investigation"),
    ],
)
def test_classifies_the_explicit_command_namespace(text: str, route: str) -> None:
    assert classify_transport_command(text) == route


def test_routes_investigation_commands_and_preserves_response_fields(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store:
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        facade = V2TransportFacade(V2TextCommandAdapter(service))

        response = facade.execute(
            "session",
            player_id="player_a",
            text="assign-role instrument_operator",
            expected_sequence=0,
        )

        assert isinstance(response, V2TransportResponse)
        assert response.route == "investigation"
        assert response.kind == "command_result"
        assert response.accepted is True
        assert response.code == "role_assigned"
        assert response.stream_id == "session"
        assert response.sequence == 1
        assert response.job_id is None
        assert event_store.latest_sequence("session") == 1


def test_routes_analysis_reads_without_touching_the_event_stream(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analysis_store,
    ):
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        job = _job_envelope()
        analysis_store.enqueue_job(
            job,
            submitted_at=datetime(2026, 7, 25, 6, 0, tzinfo=UTC),
        )
        facade = V2TransportFacade(
            V2TextCommandAdapter(service),
            V2AnalysisTextCommandAdapter(V2AnalysisPresentationService(analysis_store)),
        )

        response = facade.execute(
            "session",
            player_id="player_a",
            text=f"analysis-status {job.job.job_id}",
            expected_sequence=999,
        )

        assert response.route == "analysis"
        assert response.kind == "analysis_status"
        assert response.accepted is True
        assert response.code == "analysis_queued"
        assert response.job_id == job.job.job_id
        assert response.stream_id is None
        assert response.sequence is None
        assert event_store.latest_sequence("session") == 0
        assert analysis_store.get_job(job.job.job_id).status.value == "queued"


def test_analysis_persistence_is_optional_and_does_not_fall_through(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store:
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        facade = V2TransportFacade(V2TextCommandAdapter(service))

        response = facade.execute(
            "session",
            player_id="player_a",
            text="analysis-status job_1",
            expected_sequence=0,
        )

        assert facade.analysis_available is False
        assert response.route == "analysis"
        assert response.code == "analysis_unavailable"
        assert response.kind == "analysis_error"
        assert response.accepted is False
        assert isinstance(response.payload, V2AnalysisTransportResponse)
        assert event_store.latest_sequence("session") == 0


def test_analysis_namespace_preserves_analysis_parse_errors(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analysis_store,
    ):
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        facade = V2TransportFacade(
            V2TextCommandAdapter(service),
            V2AnalysisTextCommandAdapter(V2AnalysisPresentationService(analysis_store)),
        )

        response = facade.execute(
            "session",
            player_id="player_a",
            text='analysis-status "unterminated',
            expected_sequence=0,
        )

        assert response.route == "analysis"
        assert response.code == "invalid_analysis_quoting"
        assert event_store.latest_sequence("session") == 0


def test_reserved_unknown_analysis_command_does_not_become_game_command(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with (
        V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store,
        V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as analysis_store,
    ):
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        facade = V2TransportFacade(
            V2TextCommandAdapter(service),
            V2AnalysisTextCommandAdapter(V2AnalysisPresentationService(analysis_store)),
        )

        response = facade.execute(
            "session",
            player_id="player_a",
            text="analysis-run job_1",
            expected_sequence=0,
        )

        assert response.route == "analysis"
        assert response.code == "unknown_analysis_command"
        assert event_store.latest_sequence("session") == 0


def test_render_session_uses_the_same_response_envelope(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as event_store:
        service = V2PersistentInvestigationService(pack, event_store)
        service.create_session("session", ["player_a"])
        facade = V2TransportFacade(V2TextCommandAdapter(service))

        response = facade.render_session("session")

        assert response.route == "investigation"
        assert response.kind == "session"
        assert response.stream_id == "session"
        assert response.sequence == 0
        assert "Investigation stream" in response.to_text()
