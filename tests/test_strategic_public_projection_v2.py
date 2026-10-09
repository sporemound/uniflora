from __future__ import annotations

import json
from datetime import UTC, datetime

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2SessionView,
    execute_command,
    initialize_event_stream,
    seal_event_stream,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource
from uniflora.v2_activity_projection import build_v2_activity_snapshot

A = "discord:private-player-a"
B = "discord:private-player-b"


def test_public_schema_24_exposes_strategy_without_private_player_or_latent_state() -> None:
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource("public-strategy")
    stream = initialize_event_stream(pack, (A, B), stream_id="public-strategy")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        V2ProposeActionCommand(player_id=A, action_id="run_synchronized_reacquisition"),
    ):
        result = execute_command(pack, stream, command, random_source=source)
        assert result.accepted, (result.code, result.message)
        stream = result.stream

    sealed = seal_event_stream(stream)
    session = V2SessionView(
        stream_id=stream.stream_id,
        state=stream.state,
        sequence=stream.state.revision,
        last_event_hash=sealed[-1].event_hash,
    )
    snapshot = build_v2_activity_snapshot(
        pack,
        session,
        revision=1,
        previous_state_head_hash=None,
        updated_at=datetime(2026, 7, 28, 20, 0, tzinfo=UTC),
    )

    assert snapshot["schemaVersion"] == "2.4.0"
    assert snapshot["contentVersion"] == "2.0.0-strategic-overhaul"
    assert {item["id"] for item in snapshot["campaignTracks"]} == {
        "case_integrity",
        "institutional_trust",
    }
    board = snapshot["strategicBoard"]
    assert board["roundIndex"] == 1
    assert board["capacityRemaining"] == 2
    assert board["proposals"][0]["currentSupporterCount"] == 0
    assert "proposerPlayerId" not in board["proposals"][0]

    major = next(
        item for item in snapshot["actions"]
        if item["id"] == "run_synchronized_reacquisition"
    )
    assert major["strategicClass"] == "commit"
    assert major["supporterCount"] == 1
    assert major["command"] == "propose-action run_synchronized_reacquisition"

    rendered = json.dumps(snapshot, sort_keys=True)
    assert A not in rendered
    assert B not in rendered
    assert "previous_state_id" not in rendered
    assert "next_state_id" not in rendered
    assert "background_variation" not in rendered
