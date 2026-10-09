from __future__ import annotations

from dataclasses import replace

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
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

HOLOGRAPHY_ROLE_IDS = {
    "reconstruction_technician",
    "phase_registration_analyst",
    "optical_systems_auditor",
    "constraint_integration_analyst",
    "artifact_validation_specialist",
    "independent_reconstruction_reviewer",
}
HOLOGRAPHY_INSTRUMENT_IDS = {
    "coherent_wavefront_bench",
    "multi_source_registration_workbench",
    "inverse_reconstruction_cluster",
    "reconstruction_validation_rig",
}
HOLOGRAPHY_ENTRY_EVIDENCE_IDS = {
    "calibration_interferogram_set",
    "registration_reference_grid",
    "reconstruction_method_record",
}
HOLOGRAPHY_DERIVED_EVIDENCE_IDS = {
    "phase_registered_constraint_field",
    "absent_volume_reconstruction",
    "reconstruction_artifact_sensitivity_report",
}
HOLOGRAPHY_EVIDENCE_IDS = HOLOGRAPHY_ENTRY_EVIDENCE_IDS | HOLOGRAPHY_DERIVED_EVIDENCE_IDS
HOLOGRAPHY_ACTION_IDS = {
    "inspect_calibration_interferograms",
    "validate_registration_reference_grid",
    "audit_reconstruction_method",
    "register_cross_location_constraints",
    "reconstruct_absent_volume",
    "test_inverse_reconstruction_artifacts",
    "compare_reconstruction_families",
    "document_incomplete_phase_coverage",
}


def _accept(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    command: V2InvestigationCommand,
) -> V2InvestigationStream:
    result = execute_command(pack, stream, command)
    assert result.accepted is True, (result.code, result.message)
    return result.stream


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


def _holography_start_stream(
    pack: V2InvestigationPack,
    *,
    stream_id: str,
) -> V2InvestigationStream:
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id=stream_id,
    )
    earlier_evidence = {
        "optical_record",
        "radio_return",
        "weather_record",
        "receiver_diagnostic",
        "controller_voice_log",
        "pilot_debrief",
        "transponder_extract",
        "fused_track_display",
        "primary_radar_plot_extract",
        "fusion_processing_record",
        "case_accession_register",
        "witness_drawing_folio",
        "historical_airspace_extract",
        "terminology_crosswalk",
        "source_dependency_graph",
        "recurrence_sampling_matrix",
    }
    updated_state = replace(
        stream.state,
        current_position_id="holographic_reconstruction",
        available_location_ids=frozenset(
            {
                "boundary_array",
                "aeronautical_incident_center",
                "aerial_phenomena_archive",
                "holography_laboratory",
            }
        ),
        players=tuple(
            replace(
                player,
                current_location_id="holography_laboratory",
                active_role_id=None,
            )
            for player in stream.state.players
        ),
        available_evidence_ids=frozenset(earlier_evidence | HOLOGRAPHY_ENTRY_EVIDENCE_IDS),
        examined_evidence_ids=frozenset(earlier_evidence),
        completed_position_ids=frozenset(
            {
                "boundary_event",
                "aeronautical_incident",
                "archive_convergence",
            }
        ),
    )
    return replace(stream, state=updated_state)


def _perform_holography_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "optical_systems_auditor")
    stream = _examine(pack, stream, "calibration_interferogram_set")
    stream = _act(pack, stream, "inspect_calibration_interferograms")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "phase_registration_analyst")
    stream = _examine(pack, stream, "registration_reference_grid")
    stream = _act(pack, stream, "validate_registration_reference_grid")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_reconstruction_reviewer")
    stream = _examine(pack, stream, "reconstruction_method_record")
    stream = _act(pack, stream, "audit_reconstruction_method")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "constraint_integration_analyst")
    stream = _act(pack, stream, "register_cross_location_constraints")
    stream = _examine(pack, stream, "phase_registered_constraint_field")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "reconstruction_technician")
    stream = _act(pack, stream, "reconstruct_absent_volume")
    stream = _examine(pack, stream, "absent_volume_reconstruction")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "artifact_validation_specialist")
    stream = _act(pack, stream, "test_inverse_reconstruction_artifacts")
    stream = _examine(
        pack,
        stream,
        "reconstruction_artifact_sensitivity_report",
    )
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_reconstruction_reviewer")
    stream = _act(pack, stream, "compare_reconstruction_families")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "phase_registration_analyst")
    return _act(pack, stream, "document_incomplete_phase_coverage")


def _draft_confirmed_holography_assessment(
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
                "The registered records constrain a stable boundary-like "
                "absence, while the interior remains method-dependent and "
                "cannot be treated as a directly observed object."
            ),
            evidence_ids=evidence_ids,
            tested_ordinary_explanation_ids=("inverse_reconstruction_artifact",),
            preserved_contradiction_ids=("stable_boundary_indeterminate_interior",),
            documented_information_gap_ids=("incomplete_angular_phase_coverage",),
            confidence="moderate",
            next_collection=(
                "Acquire synchronized independent observations from missing "
                "angles with retained raw phase and timing metadata."
            ),
            minority_view=(
                "A shared unknown source-processing error could still account "
                "for some features that survive the tested artifact families."
            ),
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


def test_holography_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[4]

    assert pack.pack.content_version == "0.10.0"
    assert position.id == "holographic_reconstruction"
    assert position.title == "The Volume Defined by Its Absence"
    assert set(position.available_evidence_ids_on_entry) == (HOLOGRAPHY_ENTRY_EVIDENCE_IDS)
    assert position.completion.minimum_examined_source_classes == 6
    assert set(position.completion.required_completed_action_ids) == (HOLOGRAPHY_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "inverse_reconstruction_artifact",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "stable_boundary_indeterminate_interior",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "incomplete_angular_phase_coverage",
    )


def test_holography_has_distinct_roles_and_validation_instruments() -> None:
    pack = load_missing_interior_pack()

    roles = {
        role.id for role in pack.roles if role.allowed_location_ids == ("holography_laboratory",)
    }
    instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "holography_laboratory"
    }

    assert roles == HOLOGRAPHY_ROLE_IDS
    assert instruments == HOLOGRAPHY_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in HOLOGRAPHY_ROLE_IDS)


def test_holography_sources_separate_calibration_method_and_models() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    calibration = sources["calibration_interferogram_set"]
    reference = sources["registration_reference_grid"]
    method = sources["reconstruction_method_record"]
    field = sources["phase_registered_constraint_field"]
    reconstruction = sources["absent_volume_reconstruction"]
    sensitivity = sources["reconstruction_artifact_sensitivity_report"]

    assert calibration.raw_or_derived == "raw"
    assert reference.raw_or_derived == "processed"
    assert method.raw_or_derived == "summary"
    assert field.raw_or_derived == "derived"
    assert reconstruction.raw_or_derived == "derived"
    assert sensitivity.raw_or_derived == "derived"
    assert (
        len(
            {
                source.source_class
                for source in sources.values()
                if source.id in HOLOGRAPHY_EVIDENCE_IDS
            }
        )
        == 6
    )
    assert "A photograph of a hidden craft" in (reconstruction.unsupported_extrapolations)
    assert "Proof that persistent features are one physical object" in (
        sensitivity.unsupported_extrapolations
    )


def test_holography_entry_excludes_all_derived_products() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_entry_sources",
    )

    assert HOLOGRAPHY_ENTRY_EVIDENCE_IDS <= stream.state.available_evidence_ids
    assert HOLOGRAPHY_DERIVED_EVIDENCE_IDS.isdisjoint(stream.state.available_evidence_ids)


def test_holography_products_unlock_in_registration_then_validation_order() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_unlock_order",
    )

    stream = _assign(pack, stream, "optical_systems_auditor")
    stream = _examine(pack, stream, "calibration_interferogram_set")
    stream = _act(pack, stream, "inspect_calibration_interferograms")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "phase_registration_analyst")
    stream = _examine(pack, stream, "registration_reference_grid")
    stream = _act(pack, stream, "validate_registration_reference_grid")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_reconstruction_reviewer")
    stream = _examine(pack, stream, "reconstruction_method_record")
    stream = _act(pack, stream, "audit_reconstruction_method")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "constraint_integration_analyst")
    stream = _act(pack, stream, "register_cross_location_constraints")

    assert "phase_registered_constraint_field" in (stream.state.available_evidence_ids)
    assert "absent_volume_reconstruction" not in (stream.state.available_evidence_ids)

    stream = _examine(pack, stream, "phase_registered_constraint_field")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "reconstruction_technician")
    stream = _act(pack, stream, "reconstruct_absent_volume")

    assert "absent_volume_reconstruction" in (stream.state.available_evidence_ids)
    assert "reconstruction_artifact_sensitivity_report" not in (stream.state.available_evidence_ids)


def test_registration_requires_prior_cross_location_records() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_cross_location_gate",
    )
    stream = replace(
        stream,
        state=replace(
            stream.state,
            examined_evidence_ids=(
                stream.state.examined_evidence_ids - {"recurrence_sampling_matrix"}
            ),
        ),
    )

    stream = _assign(pack, stream, "optical_systems_auditor")
    stream = _examine(pack, stream, "calibration_interferogram_set")
    stream = _act(pack, stream, "inspect_calibration_interferograms")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "phase_registration_analyst")
    stream = _examine(pack, stream, "registration_reference_grid")
    stream = _act(pack, stream, "validate_registration_reference_grid")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "independent_reconstruction_reviewer")
    stream = _examine(pack, stream, "reconstruction_method_record")
    stream = _act(pack, stream, "audit_reconstruction_method")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "constraint_integration_analyst")

    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="register_cross_location_constraints",
        ),
    )

    assert result.accepted is False
    assert result.code == "required_evidence_missing"
    assert "recurrence_sampling_matrix" in result.message


def test_holography_actions_record_artifact_test_conflict_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_effects",
    )
    stream = _perform_holography_investigation(pack, stream)

    assert HOLOGRAPHY_ACTION_IDS <= stream.state.completed_action_ids
    assert "inverse_reconstruction_artifact" in (stream.state.tested_ordinary_explanation_ids)
    assert "stable_boundary_indeterminate_interior" in (stream.state.preserved_contradiction_ids)
    assert "incomplete_angular_phase_coverage" in (stream.state.documented_information_gap_ids)


def test_model_centric_assessment_cannot_complete_position() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_source_class_gate",
    )
    stream = _perform_holography_investigation(pack, stream)
    stream = _draft_confirmed_holography_assessment(
        pack,
        stream,
        assessment_id="model_only",
        evidence_ids=(
            "calibration_interferogram_set",
            "absent_volume_reconstruction",
        ),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="model_only",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_confirmed_holography_assessment_unlocks_subsurface_position() -> None:
    pack = load_missing_interior_pack()
    stream = _holography_start_stream(
        pack,
        stream_id="holography_completion",
    )
    stream = _perform_holography_investigation(pack, stream)
    stream = _draft_confirmed_holography_assessment(
        pack,
        stream,
        assessment_id="holography_assessment",
        evidence_ids=(
            "calibration_interferogram_set",
            "registration_reference_grid",
            "reconstruction_method_record",
            "phase_registered_constraint_field",
            "absent_volume_reconstruction",
            "reconstruction_artifact_sensitivity_report",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="holography_assessment",
        ),
    )

    assert stream.state.current_position_id == "subsurface_resonance"
    assert "subsurface_resonance_station" in (stream.state.available_location_ids)
    assert "seismic_array_waveform_set" in (stream.state.available_evidence_ids)


def test_holography_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    content = [
        pack.locations[3].description,
        pack.positions[3].title,
    ]
    content.extend(role.description for role in pack.roles if role.id in HOLOGRAPHY_ROLE_IDS)
    content.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in HOLOGRAPHY_INSTRUMENT_IDS
    )
    content.extend(
        source.provenance
        for source in pack.evidence_sources
        if source.id in HOLOGRAPHY_EVIDENCE_IDS
    )
    content.extend(
        action.description for action in pack.actions if action.id in HOLOGRAPHY_ACTION_IDS
    )

    assert all("skeleton" not in item.casefold() for item in content)
    assert all(item.id != "holographic_volume_model" for item in pack.evidence_sources)
    assert all(item.id != "review_holographic_model" for item in pack.actions)
