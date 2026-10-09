from __future__ import annotations

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2InvestigationCommand,
    V2InvestigationStream,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    execute_command,
    initialize_event_stream,
)

BOUNDARY_ROLE_IDS = {
    "field_observer",
    "instrument_operator",
    "atmospheric_analyst",
    "signal_correlator",
    "protocol_auditor",
}
BOUNDARY_INSTRUMENT_IDS = {
    "optical_array",
    "radio_receiver",
    "weather_station",
}
BOUNDARY_EVIDENCE_IDS = {
    "optical_record",
    "radio_return",
    "weather_record",
    "receiver_diagnostic",
}
BOUNDARY_ACTION_IDS = {
    "inspect_optical_record",
    "calibrate_radio_receiver",
    "request_weather_record",
    "compare_source_timing",
    "test_atmospheric_propagation",
    "document_upper_atmosphere_gap",
}


def _accept(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    command: V2InvestigationCommand,
) -> V2InvestigationStream:
    result = execute_command(pack, stream, command)
    assert result.accepted is True, (result.code, result.message)
    return result.stream


def _begin_orientation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    return _accept(
        pack,
        stream,
        V2BeginInvestigationCommand(player_id="player_a"),
    )


def _assign(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    role_id: str,
) -> V2InvestigationStream:
    return _accept(
        pack,
        stream,
        V2AssignRoleCommand(player_id="player_a", role_id=role_id),
    )


def _release(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    return _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )


def _examine(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    evidence_id: str,
) -> V2InvestigationStream:
    return _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id=evidence_id,
        ),
    )


def _act(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    action_id: str,
) -> V2InvestigationStream:
    return _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id=action_id,
        ),
    )


def _perform_boundary_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "field_observer")
    stream = _examine(pack, stream, "optical_record")
    stream = _act(pack, stream, "inspect_optical_record")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "instrument_operator")
    stream = _examine(pack, stream, "radio_return")
    stream = _act(pack, stream, "calibrate_radio_receiver")
    stream = _examine(pack, stream, "receiver_diagnostic")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "atmospheric_analyst")
    stream = _act(pack, stream, "request_weather_record")
    stream = _examine(pack, stream, "weather_record")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "signal_correlator")
    stream = _act(pack, stream, "compare_source_timing")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "atmospheric_analyst")
    stream = _act(pack, stream, "test_atmospheric_propagation")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "protocol_auditor")
    return _act(pack, stream, "document_upper_atmosphere_gap")


def test_boundary_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[1]

    assert pack.pack.title == "The Missing Interior"
    assert pack.pack.content_version == "0.10.0"
    assert position.id == "boundary_event"
    assert position.title == "First Return"
    assert position.available_evidence_ids_on_entry == (
        "optical_record",
        "radio_return",
    )
    assert position.completion.minimum_examined_source_classes == 3
    assert set(position.completion.required_completed_action_ids) == (BOUNDARY_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "atmospheric_propagation",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "optical_radio_timing_offset",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "upper_atmosphere_conditions",
    )


def test_boundary_array_has_distinct_temporary_roles_and_instruments() -> None:
    pack = load_missing_interior_pack()

    boundary_roles = {
        role.id for role in pack.roles if role.allowed_location_ids == ("boundary_array",)
    }
    boundary_instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "boundary_array"
    }

    assert boundary_roles == BOUNDARY_ROLE_IDS
    assert boundary_instruments == BOUNDARY_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in BOUNDARY_ROLE_IDS)


def test_boundary_sources_preserve_processing_and_epistemic_limits() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    optical = sources["optical_record"]
    radio = sources["radio_return"]
    weather = sources["weather_record"]
    diagnostic = sources["receiver_diagnostic"]

    assert optical.raw_or_derived == "raw"
    assert radio.raw_or_derived == "processed"
    assert radio.processing_history
    assert weather.source_class == "environmental_measurement"
    assert diagnostic.source_class == "instrument_diagnostic"
    assert diagnostic.independence_group == radio.independence_group
    assert "Exact distance" in optical.unsupported_extrapolations
    assert "Exact object shape" in radio.unsupported_extrapolations
    assert any("upper-atmosphere" in item.casefold() for item in weather.limitations)


def test_initial_state_withholds_weather_and_receiver_diagnostic() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="boundary_locked_sources",
    )
    stream = _begin_orientation(pack, stream)

    assert stream.state.available_evidence_ids == {
        "optical_record",
        "radio_return",
    }
    assert "weather_record" not in stream.state.available_evidence_ids
    assert "receiver_diagnostic" not in stream.state.available_evidence_ids


def test_calibration_and_request_actions_unlock_dependent_records() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="boundary_unlocks",
    )
    stream = _begin_orientation(pack, stream)

    stream = _assign(pack, stream, "instrument_operator")
    stream = _examine(pack, stream, "radio_return")
    stream = _act(pack, stream, "calibrate_radio_receiver")

    assert "receiver_diagnostic" in stream.state.available_evidence_ids
    assert "weather_record" not in stream.state.available_evidence_ids

    stream = _release(pack, stream)
    stream = _assign(pack, stream, "atmospheric_analyst")
    stream = _act(pack, stream, "request_weather_record")

    assert "weather_record" in stream.state.available_evidence_ids


def test_completed_actions_retain_conflict_explanation_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="boundary_effects",
    )
    stream = _begin_orientation(pack, stream)
    stream = _perform_boundary_investigation(pack, stream)

    assert BOUNDARY_ACTION_IDS <= stream.state.completed_action_ids
    assert stream.state.tested_ordinary_explanation_ids == {"atmospheric_propagation"}
    assert stream.state.preserved_contradiction_ids == {"optical_radio_timing_offset"}
    assert stream.state.documented_information_gap_ids == {"upper_atmosphere_conditions"}


def test_two_source_classes_cannot_complete_boundary_position() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="boundary_source_class_gate",
    )
    stream = _begin_orientation(pack, stream)
    stream = _perform_boundary_investigation(pack, stream)
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="insufficient_sources",
            statement="The records remain incomplete.",
            evidence_ids=("optical_record", "radio_return"),
            tested_ordinary_explanation_ids=("atmospheric_propagation",),
            preserved_contradiction_ids=("optical_radio_timing_offset",),
            documented_information_gap_ids=("upper_atmosphere_conditions",),
            confidence="low",
            next_collection="Obtain a wider atmospheric profile.",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="insufficient_sources",
        ),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="insufficient_sources",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_boundary_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    boundary_text = [
        pack.locations[0].description,
        pack.positions[0].title,
    ]
    boundary_text.extend(role.description for role in pack.roles if role.id in BOUNDARY_ROLE_IDS)
    boundary_text.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in BOUNDARY_INSTRUMENT_IDS
    )
    boundary_text.extend(
        source.provenance for source in pack.evidence_sources if source.id in BOUNDARY_EVIDENCE_IDS
    )
    boundary_text.extend(
        action.description for action in pack.actions if action.id in BOUNDARY_ACTION_IDS
    )

    assert all("skeleton" not in text.casefold() for text in boundary_text)
