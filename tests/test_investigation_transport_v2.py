from __future__ import annotations

from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2ApplicationCommandResult,
    V2AssignRoleCommand,
    V2CommandParseError,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2MovePlayerCommand,
    V2PerformActionCommand,
    V2PersistentInvestigationService,
    V2ReleaseRoleCommand,
    V2SQLiteEventStore,
    V2TextCommandAdapter,
    parse_user_command,
    render_application_result,
    render_session_view,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def test_parses_role_release_and_movement_commands() -> None:
    assert parse_user_command(
        "/role instrument_operator",
        player_id="player_a",
    ) == V2AssignRoleCommand(
        player_id="player_a",
        role_id="instrument_operator",
    )
    assert parse_user_command(
        "v2 release-role",
        player_id="player_a",
    ) == V2ReleaseRoleCommand(player_id="player_a")
    assert parse_user_command(
        "go boundary_array",
        player_id="player_a",
    ) == V2MovePlayerCommand(
        player_id="player_a",
        location_id="boundary_array",
    )


def test_parses_evidence_action_and_assessment_commands() -> None:
    assert parse_user_command(
        "inspect optical_record",
        player_id="player_a",
    ) == V2ExamineEvidenceCommand(
        player_id="player_a",
        evidence_id="optical_record",
    )
    assert parse_user_command(
        "act inspect_optical_record",
        player_id="player_a",
    ) == V2PerformActionCommand(
        player_id="player_a",
        action_id="inspect_optical_record",
    )
    assert parse_user_command(
        "confirm assessment_one",
        player_id="player_b",
    ) == V2ConfirmAssessmentCommand(
        player_id="player_b",
        assessment_id="assessment_one",
    )
    assert parse_user_command(
        "complete-position assessment_one",
        player_id="player_b",
    ) == V2CompletePositionCommand(
        player_id="player_b",
        assessment_id="assessment_one",
    )


def test_parses_a_structured_draft_assessment() -> None:
    command = parse_user_command(
        "draft-assessment assessment_one "
        '--statement "The records converge without fixing distance." '
        "--evidence optical_record,radio_return "
        "--ordinary atmospheric_propagation "
        "--contradiction optical_radio_timing_offset "
        "--gap upper_atmosphere_conditions "
        "--confidence moderate "
        '--next-collection "Retrieve regional weather data." '
        '--minority-view "The timing offset may be instrumental."',
        player_id="player_a",
    )

    assert command == V2DraftAssessmentCommand(
        player_id="player_a",
        assessment_id="assessment_one",
        statement="The records converge without fixing distance.",
        evidence_ids=("optical_record", "radio_return"),
        tested_ordinary_explanation_ids=("atmospheric_propagation",),
        preserved_contradiction_ids=("optical_radio_timing_offset",),
        documented_information_gap_ids=("upper_atmosphere_conditions",),
        confidence="moderate",
        next_collection="Retrieve regional weather data.",
        minority_view="The timing offset may be instrumental.",
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty_command"),
        ("invent-answer", "unknown_command"),
        ("move", "invalid_arguments"),
        ('draft assessment --statement "unfinished', "invalid_quoting"),
        (
            'draft assessment --statement "text" --evidence optical_record --confidence certain',
            "invalid_confidence",
        ),
    ],
)
def test_rejects_invalid_explicit_commands(text: str, code: str) -> None:
    with pytest.raises(V2CommandParseError) as raised:
        parse_user_command(text, player_id="player_a")

    assert raised.value.code == code


def test_rejects_duplicate_draft_ids() -> None:
    with pytest.raises(
        V2CommandParseError,
        match="duplicate IDs",
    ):
        parse_user_command(
            'draft assessment --statement "text" --evidence optical_record,optical_record',
            player_id="player_a",
        )


def test_renders_accepted_and_rejected_results(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])
        accepted = service.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="instrument_operator",
            ),
            expected_sequence=0,
        )
        rejected = service.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="protocol_auditor",
            ),
            expected_sequence=1,
        )

    accepted_rendered = render_application_result(accepted)
    rejected_rendered = render_application_result(rejected)

    assert accepted_rendered.accepted is True
    assert accepted_rendered.code == "role_assigned"
    assert accepted_rendered.sequence == 1
    assert "Accepted:" in accepted_rendered.to_text()
    assert "Event: V2RoleAssignedEvent" in accepted_rendered.to_text()

    assert rejected_rendered.accepted is False
    assert rejected_rendered.code == "role_already_assigned"
    assert rejected_rendered.sequence == 1
    assert "Rejected:" in rejected_rendered.to_text()
    assert "Event: none" in rejected_rendered.to_text()


def test_session_rendering_is_deterministic(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        created = service.create_session(
            "session",
            ["player_b", "player_a"],
        )

    rendered = render_session_view(created.session)
    text = rendered.to_text()

    assert rendered.kind == "session"
    assert rendered.sequence == 0
    assert text.index("Player player_a") < text.index("Player player_b")
    assert "Available evidence: optical_record, radio_return" in text


def test_text_adapter_returns_parse_error_without_appending(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])
        adapter = V2TextCommandAdapter(service)

        response = adapter.execute(
            "session",
            player_id="player_a",
            text="move",
            expected_sequence=0,
        )

        assert response.kind == "parse_error"
        assert response.accepted is False
        assert response.code == "invalid_arguments"
        assert response.sequence is None
        assert store.latest_sequence("session") == 0


def test_text_adapter_executes_and_persists_a_typed_command(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])
        adapter = V2TextCommandAdapter(service)

        response = adapter.execute(
            "session",
            player_id="player_a",
            text="assign-role instrument_operator",
            expected_sequence=0,
        )

        assert response.kind == "command_result"
        assert response.accepted is True
        assert response.code == "role_assigned"
        assert response.sequence == 1
        assert store.latest_sequence("session") == 1

        session_response = adapter.render_session("session")
        assert "instrument_operator" in session_response.to_text()
