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
    V2MovePlayerCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    execute_command,
    initialize_event_stream,
)

AERONAUTICAL_ROLE_IDS = {
    "incident_reconstructor",
    "controller_records_analyst",
    "pilot_testimony_analyst",
    "operational_sensor_auditor",
    "navigation_records_examiner",
    "independent_verifier",
}
AERONAUTICAL_INSTRUMENT_IDS = {
    "communications_recorder",
    "surveillance_radar_archive",
    "transponder_data_archive",
    "incident_fusion_console",
}
AERONAUTICAL_EVIDENCE_IDS = {
    "controller_voice_log",
    "pilot_debrief",
    "transponder_extract",
    "fused_track_display",
    "primary_radar_plot_extract",
    "fusion_processing_record",
}
AERONAUTICAL_ACTION_IDS = {
    "review_controller_voice_log",
    "review_pilot_debrief",
    "inspect_transponder_extract",
    "request_primary_radar_plot",
    "audit_fusion_processing",
    "reconstruct_relative_bearings",
    "compare_boundary_and_airspace_timing",
    "test_fusion_interpolation",
    "document_unretained_secondary_feed_gap",
}
AERONAUTICAL_ENTRY_EVIDENCE_IDS = {
    "controller_voice_log",
    "pilot_debrief",
    "transponder_extract",
    "fused_track_display",
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


def _complete_boundary_position(
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
    stream = _act(pack, stream, "document_upper_atmosphere_gap")
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="boundary_assessment",
            statement=(
                "Optical, radio, and environmental records share an event "
                "window without fixing a physical trajectory."
            ),
            evidence_ids=(
                "optical_record",
                "radio_return",
                "weather_record",
            ),
            tested_ordinary_explanation_ids=("atmospheric_propagation",),
            preserved_contradiction_ids=("optical_radio_timing_offset",),
            documented_information_gap_ids=("upper_atmosphere_conditions",),
            confidence="moderate",
            next_collection="Obtain wider atmospheric and directional coverage.",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="boundary_assessment",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="boundary_assessment",
        ),
    )


def _reach_aeronautical_position(
    pack: V2InvestigationPack,
    *,
    stream_id: str,
) -> V2InvestigationStream:
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id=stream_id,
    )
    stream = _begin_orientation(pack, stream)
    stream = _complete_boundary_position(pack, stream)

    for player_id in ("player_a", "player_b"):
        stream = _accept(
            pack,
            stream,
            V2MovePlayerCommand(
                player_id=player_id,
                location_id="aeronautical_incident_center",
            ),
        )

    return stream


def _perform_aeronautical_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "controller_records_analyst")
    stream = _examine(pack, stream, "controller_voice_log")
    stream = _act(pack, stream, "review_controller_voice_log")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "pilot_testimony_analyst")
    stream = _examine(pack, stream, "pilot_debrief")
    stream = _act(pack, stream, "review_pilot_debrief")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "navigation_records_examiner")
    stream = _examine(pack, stream, "transponder_extract")
    stream = _act(pack, stream, "inspect_transponder_extract")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "operational_sensor_auditor")
    stream = _examine(pack, stream, "fused_track_display")
    stream = _act(pack, stream, "request_primary_radar_plot")
    stream = _examine(pack, stream, "primary_radar_plot_extract")
    stream = _examine(pack, stream, "fusion_processing_record")
    stream = _act(pack, stream, "audit_fusion_processing")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "incident_reconstructor")
    stream = _act(pack, stream, "reconstruct_relative_bearings")
    stream = _act(pack, stream, "compare_boundary_and_airspace_timing")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "operational_sensor_auditor")
    stream = _act(pack, stream, "test_fusion_interpolation")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_verifier")
    return _act(pack, stream, "document_unretained_secondary_feed_gap")


def _draft_confirmed_assessment(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    *,
    assessment_id: str,
    evidence_ids: tuple[str, ...],
) -> V2InvestigationStream:
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id=assessment_id,
            statement=(
                "No single continuous trajectory satisfies all retained "
                "aviation and Boundary Array constraints."
            ),
            evidence_ids=evidence_ids,
            tested_ordinary_explanation_ids=("track_fusion_interpolation",),
            preserved_contradiction_ids=("trajectory_solution_divergence",),
            documented_information_gap_ids=("unretained_secondary_sensor_data",),
            confidence="moderate",
            next_collection=(
                "Recover the missing secondary feed or equivalent independent "
                "coverage before assigning a physical trajectory."
            ),
            minority_view=("Unrecorded processing may account for more of the disagreement."),
        ),
    )
    return _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id=assessment_id,
        ),
    )


def test_aeronautical_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[2]

    assert pack.pack.content_version == "0.10.0"
    assert position.id == "aeronautical_incident"
    assert position.title == "The Track That Will Not Close"
    assert set(position.available_evidence_ids_on_entry) == (AERONAUTICAL_ENTRY_EVIDENCE_IDS)
    assert position.completion.minimum_examined_source_classes == 5
    assert set(position.completion.required_completed_action_ids) == (AERONAUTICAL_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "track_fusion_interpolation",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "trajectory_solution_divergence",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "unretained_secondary_sensor_data",
    )


def test_aeronautical_center_has_distinct_roles_and_operational_systems() -> None:
    pack = load_missing_interior_pack()

    roles = {
        role.id
        for role in pack.roles
        if role.allowed_location_ids == ("aeronautical_incident_center",)
    }
    instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "aeronautical_incident_center"
    }

    assert roles == AERONAUTICAL_ROLE_IDS
    assert instruments == AERONAUTICAL_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in AERONAUTICAL_ROLE_IDS)


def test_aviation_sources_distinguish_testimony_plots_and_fusion() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    controller = sources["controller_voice_log"]
    pilot = sources["pilot_debrief"]
    transponder = sources["transponder_extract"]
    fused = sources["fused_track_display"]
    primary = sources["primary_radar_plot_extract"]
    processing = sources["fusion_processing_record"]

    assert controller.raw_or_derived == "raw"
    assert pilot.raw_or_derived == "testimony"
    assert transponder.raw_or_derived == "processed"
    assert primary.raw_or_derived == "processed"
    assert fused.raw_or_derived == "derived"
    assert fused.processing_history
    assert fused.independence_group == processing.independence_group
    assert fused.independence_group != primary.independence_group
    assert "Exact physical trajectory" in fused.unsupported_extrapolations
    assert any("does not directly establish" in item for item in primary.limitations)


def test_boundary_completion_unlocks_only_aeronautical_entry_sources() -> None:
    pack = load_missing_interior_pack()
    stream = _reach_aeronautical_position(
        pack,
        stream_id="aeronautical_entry_sources",
    )

    assert stream.state.current_position_id == "aeronautical_incident"
    assert AERONAUTICAL_ENTRY_EVIDENCE_IDS <= (stream.state.available_evidence_ids)
    assert "primary_radar_plot_extract" not in stream.state.available_evidence_ids
    assert "fusion_processing_record" not in stream.state.available_evidence_ids


def test_primary_plot_request_unlocks_source_and_processing_record() -> None:
    pack = load_missing_interior_pack()
    stream = _reach_aeronautical_position(
        pack,
        stream_id="aeronautical_plot_unlock",
    )

    stream = _assign(pack, stream, "operational_sensor_auditor")
    stream = _examine(pack, stream, "fused_track_display")
    stream = _act(pack, stream, "request_primary_radar_plot")

    assert "primary_radar_plot_extract" in stream.state.available_evidence_ids
    assert "fusion_processing_record" in stream.state.available_evidence_ids


def test_completed_actions_preserve_explanation_conflict_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = _reach_aeronautical_position(
        pack,
        stream_id="aeronautical_effects",
    )
    stream = _perform_aeronautical_investigation(pack, stream)

    assert AERONAUTICAL_ACTION_IDS <= stream.state.completed_action_ids
    assert "track_fusion_interpolation" in (stream.state.tested_ordinary_explanation_ids)
    assert "trajectory_solution_divergence" in (stream.state.preserved_contradiction_ids)
    assert "unretained_secondary_sensor_data" in (stream.state.documented_information_gap_ids)


def test_fused_track_alone_cannot_complete_aeronautical_position() -> None:
    pack = load_missing_interior_pack()
    stream = _reach_aeronautical_position(
        pack,
        stream_id="aeronautical_source_class_gate",
    )
    stream = _perform_aeronautical_investigation(pack, stream)
    stream = _draft_confirmed_assessment(
        pack,
        stream,
        assessment_id="fused_only",
        evidence_ids=("fused_track_display",),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="fused_only",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_confirmed_all_source_assessment_unlocks_archive_position() -> None:
    pack = load_missing_interior_pack()
    stream = _reach_aeronautical_position(
        pack,
        stream_id="aeronautical_completion",
    )
    stream = _perform_aeronautical_investigation(pack, stream)
    stream = _draft_confirmed_assessment(
        pack,
        stream,
        assessment_id="aeronautical_assessment",
        evidence_ids=(
            "controller_voice_log",
            "pilot_debrief",
            "transponder_extract",
            "fused_track_display",
            "primary_radar_plot_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="aeronautical_assessment",
        ),
    )

    assert stream.state.current_position_id == "archive_convergence"
    assert "aerial_phenomena_archive" in stream.state.available_location_ids
    assert {
        "case_accession_register",
        "witness_drawing_folio",
        "historical_airspace_extract",
        "terminology_crosswalk",
    } <= stream.state.available_evidence_ids


def test_aeronautical_cross_location_comparison_requires_boundary_records() -> None:
    pack = load_missing_interior_pack()
    action = next(
        item for item in pack.actions if item.id == "compare_boundary_and_airspace_timing"
    )

    assert {"optical_record", "radio_return"} <= set(
        action.prerequisites.required_examined_evidence_ids
    )
    assert action.location_id == "aeronautical_incident_center"


def test_aeronautical_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    content = [
        pack.locations[1].description,
        pack.positions[1].title,
    ]
    content.extend(role.description for role in pack.roles if role.id in AERONAUTICAL_ROLE_IDS)
    content.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in AERONAUTICAL_INSTRUMENT_IDS
    )
    content.extend(
        source.provenance
        for source in pack.evidence_sources
        if source.id in AERONAUTICAL_EVIDENCE_IDS
    )
    content.extend(
        action.description for action in pack.actions if action.id in AERONAUTICAL_ACTION_IDS
    )

    assert all("skeleton" not in item.casefold() for item in content)
