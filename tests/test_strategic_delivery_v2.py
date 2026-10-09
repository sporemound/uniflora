from __future__ import annotations

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PassCapacityCommand,
    V2ProposeActionCommand,
    V2SupportActionCommand,
    V2ViewStrategicBoardCommand,
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.parsing import parse_user_command
from uniflora.engine.v2.delivery import build_position_guide, guided_suggestions
from uniflora.engine.v2.stochastic import V2SeededRandomSource

A = "discord:delivery-a"
B = "discord:delivery-b"


def test_parser_exposes_the_strategic_command_namespace() -> None:
    assert isinstance(parse_user_command("board", player_id=A), V2ViewStrategicBoardCommand)
    assert isinstance(
        parse_user_command(
            "propose-action run_synchronized_reacquisition",
            player_id=A,
        ),
        V2ProposeActionCommand,
    )
    assert isinstance(
        parse_user_command("support-action proposal_123", player_id=B),
        V2SupportActionCommand,
    )
    assert isinstance(
        parse_user_command("pass-capacity", player_id=A),
        V2PassCapacityCommand,
    )


def test_position_guide_shows_board_costs_and_optional_major_operation() -> None:
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource("delivery")
    stream = initialize_event_stream(pack, (A, B), stream_id="delivery")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"),
        V2AssignRoleCommand(player_id=A, role_id="signal_correlator"),
    ):
        result = execute_command(pack, stream, command, random_source=source)
        assert result.accepted, (result.code, result.message)
        stream = result.stream

    guide = build_position_guide(pack, stream.state, A)
    assert "**Strategic board**" in guide
    assert "capacity 3/3" in guide
    assert "Run synchronized reacquisition" in guide
    assert "propose + 1 supporter(s)" in guide

    suggestions = guided_suggestions(pack, stream.state, A)
    assert any(
        item.command == "propose-action run_synchronized_reacquisition"
        for item in suggestions
    )
