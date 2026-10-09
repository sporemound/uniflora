from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2ActionPerformedEvent,
    V2AssessmentConfirmedEvent,
    V2AssessmentDraftedEvent,
    V2AssessmentState,
    V2AssignRoleCommand,
    V2EventEnvelope,
    V2EvidenceExaminedEvent,
    V2IntegrityError,
    V2JoinInvestigationCommand,
    V2PlayerMovedEvent,
    V2PositionCompletedEvent,
    V2ReleasedRole,
    V2RoleAssignedEvent,
    V2RoleReleasedEvent,
    V2SerializationError,
    V2SnapshotError,
    create_snapshot_envelope,
    deserialize_event,
    deserialize_event_envelope,
    deserialize_snapshot_envelope,
    execute_command,
    initialize_event_stream,
    seal_event_stream,
    serialize_event,
    serialize_event_envelope,
    serialize_snapshot_envelope,
    verify_event_envelopes,
    verify_snapshot_envelope,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _stream(pack: V2InvestigationPack, *, stream_id: str = "boundary_session"):
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id=stream_id,
    )
    result = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    assert result.accepted is True
    return result.stream


def _all_event_shapes(pack: V2InvestigationPack):
    initial = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="shape_session",
    ).events[0]
    assessment = V2AssessmentState(
        id="assessment_one",
        author_player_id="player_a",
        statement="A bounded synthetic assessment.",
        evidence_ids=frozenset({"optical_record"}),
        tested_ordinary_explanation_ids=frozenset({"atmospheric_propagation"}),
        preserved_contradiction_ids=frozenset({"timing_offset"}),
        documented_information_gap_ids=frozenset({"upper_air"}),
        confidence="moderate",
        next_collection="Obtain a second calibrated record.",
        minority_view="A processing artifact remains possible.",
    )

    return (
        initial,
        V2RoleAssignedEvent(
            stream_id="shape_session",
            sequence=1,
            player_id="player_a",
            role_id="instrument_operator",
        ),
        V2RoleReleasedEvent(
            stream_id="shape_session",
            sequence=2,
            player_id="player_a",
            role_id="instrument_operator",
        ),
        V2PlayerMovedEvent(
            stream_id="shape_session",
            sequence=3,
            player_id="player_a",
            from_location_id="boundary_array",
            to_location_id="remote_archive",
        ),
        V2EvidenceExaminedEvent(
            stream_id="shape_session",
            sequence=4,
            player_id="player_a",
            evidence_id="optical_record",
        ),
        V2ActionPerformedEvent(
            stream_id="shape_session",
            sequence=5,
            player_id="player_a",
            action_id="compare_sources",
            unlocked_evidence_ids=frozenset({"weather_record", "diagnostic"}),
            tested_ordinary_explanation_ids=frozenset({"atmospheric_propagation"}),
            preserved_contradiction_ids=frozenset({"timing_offset"}),
            documented_information_gap_ids=frozenset({"upper_air"}),
        ),
        V2AssessmentDraftedEvent(
            stream_id="shape_session",
            sequence=6,
            assessment=assessment,
        ),
        V2AssessmentConfirmedEvent(
            stream_id="shape_session",
            sequence=7,
            player_id="player_b",
            assessment_id="assessment_one",
        ),
        V2PositionCompletedEvent(
            stream_id="shape_session",
            sequence=8,
            player_id="player_b",
            position_id="boundary_event",
            assessment_id="assessment_one",
            released_roles=(
                V2ReleasedRole(
                    player_id="player_a",
                    role_id="instrument_operator",
                ),
            ),
        ),
    )


def test_event_serialization_round_trips_all_event_shapes(
    pack: V2InvestigationPack,
) -> None:
    for event in _all_event_shapes(pack):
        assert deserialize_event(serialize_event(event)) == event


def test_event_serialization_is_canonical_for_unordered_effects() -> None:
    first = V2ActionPerformedEvent(
        stream_id="canonical_session",
        sequence=1,
        player_id="player_a",
        action_id="compare_sources",
        unlocked_evidence_ids=frozenset({"zeta", "alpha"}),
    )
    second = V2ActionPerformedEvent(
        stream_id="canonical_session",
        sequence=1,
        player_id="player_a",
        action_id="compare_sources",
        unlocked_evidence_ids=frozenset({"alpha", "zeta"}),
    )

    assert serialize_event(first) == serialize_event(second)
    assert b'"unlocked_evidence_ids":["alpha","zeta"]' in serialize_event(first)


def test_unknown_event_type_is_rejected(pack: V2InvestigationPack) -> None:
    event = _all_event_shapes(pack)[0]
    record = json.loads(serialize_event(event))
    record["event_type"] = "invented_event"

    with pytest.raises(V2SerializationError, match="unsupported event type"):
        deserialize_event(json.dumps(record))


def test_sealed_stream_builds_a_deterministic_hash_chain(
    pack: V2InvestigationPack,
) -> None:
    stream = _stream(pack)
    envelopes = seal_event_stream(stream)

    assert len(envelopes) == len(stream.events)
    assert envelopes[0].previous_hash is None
    assert envelopes[1].previous_hash == envelopes[0].event_hash
    assert verify_event_envelopes(envelopes) == stream.state
    assert seal_event_stream(stream) == envelopes


def test_tampered_envelope_payload_is_rejected(
    pack: V2InvestigationPack,
) -> None:
    envelope = seal_event_stream(_stream(pack))[1]
    record = json.loads(serialize_event_envelope(envelope))
    record["event"]["payload"]["role_id"] = "protocol_auditor"

    with pytest.raises(V2IntegrityError, match="hash does not match"):
        deserialize_event_envelope(json.dumps(record))


def test_broken_previous_hash_is_rejected(
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_stream(pack))
    broken = replace(envelopes[1], previous_hash="0" * 64)

    with pytest.raises(V2IntegrityError, match="invalid previous hash"):
        verify_event_envelopes((envelopes[0], broken))


def test_event_envelope_serialization_round_trips(
    pack: V2InvestigationPack,
) -> None:
    envelope = seal_event_stream(_stream(pack))[1]

    assert deserialize_event_envelope(serialize_event_envelope(envelope)) == envelope


def test_schema_two_player_join_envelope_replays_without_changing_its_hash(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(pack, ["player_a"], stream_id="legacy_join")
    result = execute_command(
        pack,
        stream,
        V2JoinInvestigationCommand(player_id="player_b"),
    )
    assert result.accepted is True

    records = [
        json.loads(serialize_event_envelope(envelope))
        for envelope in seal_event_stream(result.stream)
    ]
    legacy_join = records[1]
    assert legacy_join["event"]["schema_version"] == 3
    legacy_join["event"]["schema_version"] = 2
    hash_material = {
        "event": legacy_join["event"],
        "previous_hash": legacy_join["previous_hash"],
        "schema_version": legacy_join["schema_version"],
    }
    legacy_join["event_hash"] = hashlib.sha256(
        json.dumps(
            hash_material,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    restored = tuple(deserialize_event_envelope(json.dumps(record)) for record in records)
    assert json.loads(serialize_event_envelope(restored[1])) == legacy_join
    assert verify_event_envelopes(restored) == result.stream.state


def test_snapshot_round_trip_is_bound_to_verified_event_chain(
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_stream(pack))
    snapshot = create_snapshot_envelope(envelopes)
    restored = deserialize_snapshot_envelope(serialize_snapshot_envelope(snapshot))

    assert restored == snapshot
    assert restored.sequence == envelopes[-1].event.sequence
    assert restored.last_event_hash == envelopes[-1].event_hash
    assert verify_snapshot_envelope(restored, envelopes) == restored.state


def test_snapshot_state_tampering_is_rejected(
    pack: V2InvestigationPack,
) -> None:
    snapshot = create_snapshot_envelope(seal_event_stream(_stream(pack)))
    record = json.loads(serialize_snapshot_envelope(snapshot))
    record["state"]["pack_id"] = "tampered_pack"

    with pytest.raises(V2SnapshotError, match="state hash"):
        deserialize_snapshot_envelope(json.dumps(record))


def test_snapshot_rejects_a_different_stream_chain(
    pack: V2InvestigationPack,
) -> None:
    first_envelopes = seal_event_stream(_stream(pack, stream_id="first_session"))
    second_envelopes = seal_event_stream(_stream(pack, stream_id="second_session"))
    snapshot = create_snapshot_envelope(first_envelopes)

    with pytest.raises(V2SnapshotError, match="stream ID"):
        verify_snapshot_envelope(snapshot, second_envelopes)


def test_event_envelope_rejects_noncanonical_hash_text(
    pack: V2InvestigationPack,
) -> None:
    event = _all_event_shapes(pack)[0]

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        V2EventEnvelope(
            event=event,
            previous_hash=None,
            event_hash="A" * 64,
        )
