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

SUBSURFACE_ROLE_IDS = {
    "seismic_array_analyst",
    "borehole_acoustics_analyst",
    "geological_context_specialist",
    "electromagnetic_coupling_auditor",
    "hydrogeology_infrastructure_examiner",
    "distributed_mode_analyst",
    "independent_geophysical_reviewer",
}
SUBSURFACE_INSTRUMENT_IDS = {
    "regional_seismic_array",
    "borehole_acoustic_string",
    "geological_context_workbench",
    "electromagnetic_induction_grid",
    "hydrogeology_infrastructure_workbench",
    "distributed_mode_analysis_cluster",
}
SUBSURFACE_ENTRY_EVIDENCE_IDS = {
    "seismic_array_waveform_set",
    "borehole_acoustic_record",
    "geological_coupling_map",
    "electromagnetic_background_survey",
}
SUBSURFACE_DERIVED_EVIDENCE_IDS = {
    "infrastructure_groundwater_exclusion_report",
    "cross_domain_coherence_model",
    "regional_mode_sensitivity_report",
}
SUBSURFACE_EVIDENCE_IDS = SUBSURFACE_ENTRY_EVIDENCE_IDS | SUBSURFACE_DERIVED_EVIDENCE_IDS
SUBSURFACE_ACTION_IDS = {
    "inspect_seismic_waveforms",
    "inspect_borehole_acoustics",
    "audit_geological_coupling_map",
    "survey_electromagnetic_background",
    "map_groundwater_and_infrastructure",
    "build_cross_domain_coherence_model",
    "test_local_coupling_and_infrastructure_resonance",
    "compare_regional_mode_models",
    "document_sparse_multiphysics_coverage",
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


def _subsurface_start_stream(
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
        "calibration_interferogram_set",
        "registration_reference_grid",
        "reconstruction_method_record",
        "phase_registered_constraint_field",
        "absent_volume_reconstruction",
        "reconstruction_artifact_sensitivity_report",
    }
    updated_state = replace(
        stream.state,
        current_position_id="subsurface_resonance",
        available_location_ids=frozenset(
            {
                "boundary_array",
                "aeronautical_incident_center",
                "aerial_phenomena_archive",
                "holography_laboratory",
                "subsurface_resonance_station",
            }
        ),
        players=tuple(
            replace(
                player,
                current_location_id="subsurface_resonance_station",
                active_role_id=None,
            )
            for player in stream.state.players
        ),
        available_evidence_ids=frozenset(earlier_evidence | SUBSURFACE_ENTRY_EVIDENCE_IDS),
        examined_evidence_ids=frozenset(earlier_evidence),
        completed_position_ids=frozenset(
            {
                "boundary_event",
                "aeronautical_incident",
                "archive_convergence",
                "holographic_reconstruction",
            }
        ),
    )
    return replace(stream, state=updated_state)


def _perform_subsurface_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "seismic_array_analyst")
    stream = _examine(pack, stream, "seismic_array_waveform_set")
    stream = _act(pack, stream, "inspect_seismic_waveforms")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "borehole_acoustics_analyst")
    stream = _examine(pack, stream, "borehole_acoustic_record")
    stream = _act(pack, stream, "inspect_borehole_acoustics")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "geological_context_specialist")
    stream = _examine(pack, stream, "geological_coupling_map")
    stream = _act(pack, stream, "audit_geological_coupling_map")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "electromagnetic_coupling_auditor")
    stream = _examine(pack, stream, "electromagnetic_background_survey")
    stream = _act(pack, stream, "survey_electromagnetic_background")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "hydrogeology_infrastructure_examiner")
    stream = _act(pack, stream, "map_groundwater_and_infrastructure")
    stream = _examine(
        pack,
        stream,
        "infrastructure_groundwater_exclusion_report",
    )
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "distributed_mode_analyst")
    stream = _act(pack, stream, "build_cross_domain_coherence_model")
    stream = _examine(pack, stream, "cross_domain_coherence_model")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_geophysical_reviewer")
    stream = _act(
        pack,
        stream,
        "test_local_coupling_and_infrastructure_resonance",
    )
    stream = _examine(pack, stream, "regional_mode_sensitivity_report")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "distributed_mode_analyst")
    stream = _act(pack, stream, "compare_regional_mode_models")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "geological_context_specialist")
    return _act(pack, stream, "document_sparse_multiphysics_coverage")


def _draft_confirmed_subsurface_assessment(
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
                "The records support a regional multiphysics response aligned "
                "with part of the inferred boundary, but they do not resolve a "
                "unique source point, cavity, material shell, or causal mechanism."
            ),
            evidence_ids=evidence_ids,
            tested_ordinary_explanation_ids=("local_geology_infrastructure_coupling",),
            preserved_contradiction_ids=("regional_coherence_without_unique_source_volume",),
            documented_information_gap_ids=("sparse_subsurface_multiphysics_coverage",),
            confidence="moderate",
            next_collection=(
                "Add dense peripheral stations, additional boreholes, "
                "conductivity profiles, groundwater controls, and complete "
                "infrastructure logs under synchronized acquisition."
            ),
            minority_view=(
                "Unrecorded shared forcing or multiple ordinary regional "
                "sources may account for the remaining coherence."
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


def test_subsurface_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[5]

    assert pack.pack.content_version == "0.10.0"
    assert position.id == "subsurface_resonance"
    assert position.title == "A Mode Without a Source Point"
    assert set(position.available_evidence_ids_on_entry) == (SUBSURFACE_ENTRY_EVIDENCE_IDS)
    assert position.completion.minimum_examined_source_classes == 7
    assert set(position.completion.required_completed_action_ids) == (SUBSURFACE_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "local_geology_infrastructure_coupling",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "regional_coherence_without_unique_source_volume",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "sparse_subsurface_multiphysics_coverage",
    )


def test_subsurface_has_distinct_roles_and_multiphysics_instruments() -> None:
    pack = load_missing_interior_pack()

    roles = {
        role.id
        for role in pack.roles
        if role.allowed_location_ids == ("subsurface_resonance_station",)
    }
    instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "subsurface_resonance_station"
    }

    assert roles == SUBSURFACE_ROLE_IDS
    assert instruments == SUBSURFACE_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in SUBSURFACE_ROLE_IDS)


def test_subsurface_sources_separate_measurement_context_and_models() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    seismic = sources["seismic_array_waveform_set"]
    acoustic = sources["borehole_acoustic_record"]
    geology = sources["geological_coupling_map"]
    electromagnetic = sources["electromagnetic_background_survey"]
    environment = sources["infrastructure_groundwater_exclusion_report"]
    model = sources["cross_domain_coherence_model"]
    sensitivity = sources["regional_mode_sensitivity_report"]

    assert seismic.raw_or_derived == "raw"
    assert acoustic.raw_or_derived == "raw"
    assert geology.raw_or_derived == "processed"
    assert electromagnetic.raw_or_derived == "processed"
    assert environment.raw_or_derived == "summary"
    assert model.raw_or_derived == "derived"
    assert sensitivity.raw_or_derived == "derived"
    assert (
        len(
            {
                source.source_class
                for source in sources.values()
                if source.id in SUBSURFACE_EVIDENCE_IDS
            }
        )
        == 7
    )
    assert "A subterranean craft or chamber" in (model.unsupported_extrapolations)
    assert "Proof of a nonlocal phenomenon" in (sensitivity.unsupported_extrapolations)


def test_subsurface_entry_excludes_derived_products() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_entry_sources",
    )

    assert SUBSURFACE_ENTRY_EVIDENCE_IDS <= stream.state.available_evidence_ids
    assert SUBSURFACE_DERIVED_EVIDENCE_IDS.isdisjoint(stream.state.available_evidence_ids)


def test_subsurface_products_unlock_in_context_model_validation_order() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_unlock_order",
    )

    stream = _assign(pack, stream, "seismic_array_analyst")
    stream = _examine(pack, stream, "seismic_array_waveform_set")
    stream = _act(pack, stream, "inspect_seismic_waveforms")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "borehole_acoustics_analyst")
    stream = _examine(pack, stream, "borehole_acoustic_record")
    stream = _act(pack, stream, "inspect_borehole_acoustics")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "geological_context_specialist")
    stream = _examine(pack, stream, "geological_coupling_map")
    stream = _act(pack, stream, "audit_geological_coupling_map")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "electromagnetic_coupling_auditor")
    stream = _examine(pack, stream, "electromagnetic_background_survey")
    stream = _act(pack, stream, "survey_electromagnetic_background")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "hydrogeology_infrastructure_examiner")
    stream = _act(pack, stream, "map_groundwater_and_infrastructure")

    assert "infrastructure_groundwater_exclusion_report" in (stream.state.available_evidence_ids)
    assert "cross_domain_coherence_model" not in (stream.state.available_evidence_ids)

    stream = _examine(
        pack,
        stream,
        "infrastructure_groundwater_exclusion_report",
    )
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "distributed_mode_analyst")
    stream = _act(pack, stream, "build_cross_domain_coherence_model")

    assert "cross_domain_coherence_model" in stream.state.available_evidence_ids
    assert "regional_mode_sensitivity_report" not in (stream.state.available_evidence_ids)


def test_subsurface_model_requires_holography_constraints() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_cross_location_gate",
    )
    stream = replace(
        stream,
        state=replace(
            stream.state,
            examined_evidence_ids=(
                stream.state.examined_evidence_ids - {"absent_volume_reconstruction"}
            ),
        ),
    )

    stream = _assign(pack, stream, "seismic_array_analyst")
    stream = _examine(pack, stream, "seismic_array_waveform_set")
    stream = _act(pack, stream, "inspect_seismic_waveforms")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "borehole_acoustics_analyst")
    stream = _examine(pack, stream, "borehole_acoustic_record")
    stream = _act(pack, stream, "inspect_borehole_acoustics")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "geological_context_specialist")
    stream = _examine(pack, stream, "geological_coupling_map")
    stream = _act(pack, stream, "audit_geological_coupling_map")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "electromagnetic_coupling_auditor")
    stream = _examine(pack, stream, "electromagnetic_background_survey")
    stream = _act(pack, stream, "survey_electromagnetic_background")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "hydrogeology_infrastructure_examiner")
    stream = _act(pack, stream, "map_groundwater_and_infrastructure")
    stream = _examine(
        pack,
        stream,
        "infrastructure_groundwater_exclusion_report",
    )
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "distributed_mode_analyst")

    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="build_cross_domain_coherence_model",
        ),
    )

    assert result.accepted is False
    assert result.code == "required_evidence_missing"
    assert "absent_volume_reconstruction" in result.message


def test_subsurface_actions_record_control_test_conflict_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_effects",
    )
    stream = _perform_subsurface_investigation(pack, stream)

    assert SUBSURFACE_ACTION_IDS <= stream.state.completed_action_ids
    assert "local_geology_infrastructure_coupling" in (stream.state.tested_ordinary_explanation_ids)
    assert "regional_coherence_without_unique_source_volume" in (
        stream.state.preserved_contradiction_ids
    )
    assert "sparse_subsurface_multiphysics_coverage" in (
        stream.state.documented_information_gap_ids
    )


def test_seismic_centric_assessment_cannot_complete_position() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_source_class_gate",
    )
    stream = _perform_subsurface_investigation(pack, stream)
    stream = _draft_confirmed_subsurface_assessment(
        pack,
        stream,
        assessment_id="seismic_only",
        evidence_ids=(
            "seismic_array_waveform_set",
            "borehole_acoustic_record",
        ),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="seismic_only",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_confirmed_subsurface_assessment_unlocks_quantum_position() -> None:
    pack = load_missing_interior_pack()
    stream = _subsurface_start_stream(
        pack,
        stream_id="subsurface_completion",
    )
    stream = _perform_subsurface_investigation(pack, stream)
    stream = _draft_confirmed_subsurface_assessment(
        pack,
        stream,
        assessment_id="subsurface_assessment",
        evidence_ids=(
            "seismic_array_waveform_set",
            "borehole_acoustic_record",
            "geological_coupling_map",
            "electromagnetic_background_survey",
            "infrastructure_groundwater_exclusion_report",
            "cross_domain_coherence_model",
            "regional_mode_sensitivity_report",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="subsurface_assessment",
        ),
    )

    assert stream.state.current_position_id == "quantum_state"
    assert "quantum_state_institute" in stream.state.available_location_ids
    assert {
        "measurement_basis_registry",
        "state_preparation_protocol",
        "synchronized_observable_dataset",
        "readout_calibration_record",
    } <= stream.state.available_evidence_ids


def test_subsurface_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    content = [
        pack.locations[4].description,
        pack.positions[4].title,
    ]
    content.extend(role.description for role in pack.roles if role.id in SUBSURFACE_ROLE_IDS)
    content.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in SUBSURFACE_INSTRUMENT_IDS
    )
    content.extend(
        source.provenance
        for source in pack.evidence_sources
        if source.id in SUBSURFACE_EVIDENCE_IDS
    )
    content.extend(
        action.description for action in pack.actions if action.id in SUBSURFACE_ACTION_IDS
    )

    assert all("skeleton" not in item.casefold() for item in content)
    assert all(item.id != "subsurface_coherence_trace" for item in pack.evidence_sources)
    assert all(item.id != "review_resonance_trace" for item in pack.actions)
    assert all(item.id != "resonance_analyst" for item in pack.roles)
    assert all(item.id != "regional_resonance_array" for item in pack.instruments)
