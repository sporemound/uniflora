from __future__ import annotations

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from uniflora.content.v2 import (
    MISSING_INTERIOR_PACK_PATH,
    V2InvestigationPack,
    load_missing_interior_pack,
)
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
    V2PositionCompletedEvent,
    V2ReleaseRoleCommand,
    deserialize_event,
    execute_command,
    initialize_event_stream,
    replay_events,
    serialize_event,
)

POSITION_STEPS = (
    (
        "boundary_event",
        "boundary_array",
        "field_observer",
        "optical_record",
        "inspect_optical_record",
        "aeronautical_incident",
        "aeronautical_incident_center",
        "controller_voice_log",
    ),
    (
        "aeronautical_incident",
        "aeronautical_incident_center",
        "controller_records_analyst",
        "controller_voice_log",
        "review_controller_voice_log",
        "archive_convergence",
        "aerial_phenomena_archive",
        "case_accession_register",
    ),
    (
        "archive_convergence",
        "aerial_phenomena_archive",
        "records_custodian",
        "case_accession_register",
        "audit_case_accessions",
        "holographic_reconstruction",
        "holography_laboratory",
        "calibration_interferogram_set",
    ),
    (
        "holographic_reconstruction",
        "holography_laboratory",
        "optical_systems_auditor",
        "calibration_interferogram_set",
        "inspect_calibration_interferograms",
        "subsurface_resonance",
        "subsurface_resonance_station",
        "seismic_array_waveform_set",
    ),
    (
        "subsurface_resonance",
        "subsurface_resonance_station",
        "seismic_array_analyst",
        "seismic_array_waveform_set",
        "inspect_seismic_waveforms",
        "quantum_state",
        "quantum_state_institute",
        "measurement_basis_registry",
    ),
    (
        "quantum_state",
        "quantum_state_institute",
        "state_preparation_operator",
        "state_preparation_protocol",
        "audit_state_preparation_protocol",
        None,
        None,
        None,
    ),
)


def _payload() -> dict[str, Any]:
    payload = yaml.safe_load(MISSING_INTERIOR_PACK_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _accept(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    command: V2InvestigationCommand,
) -> V2InvestigationStream:
    result = execute_command(pack, stream, command)
    assert result.accepted is True, (result.code, result.message)
    return result.stream


def _complete_boundary_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="field_observer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="optical_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_optical_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="radio_return",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="calibrate_radio_receiver",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="receiver_diagnostic",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="atmospheric_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="request_weather_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="weather_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="signal_correlator",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_source_timing",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="atmospheric_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="test_atmospheric_propagation",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="protocol_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_upper_atmosphere_gap",
        ),
    )

    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_1",
            statement=(
                "Optical, radio, and local environmental records converge on "
                "one event window without establishing a physical trajectory."
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
            next_collection=(
                "Obtain a wider atmospheric profile and independent directional "
                "coverage before attempting trajectory reconstruction."
            ),
            minority_view=(
                "The remaining timing offset may still reflect unrecorded receiver "
                "state rather than the event."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_1",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_1",
        ),
    )


def _complete_aeronautical_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != "aeronautical_incident_center":
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id="aeronautical_incident_center",
                ),
            )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="controller_records_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="controller_voice_log",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="review_controller_voice_log",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="pilot_testimony_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="pilot_debrief",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="review_pilot_debrief",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="navigation_records_examiner",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="transponder_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_transponder_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="operational_sensor_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="fused_track_display",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="request_primary_radar_plot",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="primary_radar_plot_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="fusion_processing_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="audit_fusion_processing",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="incident_reconstructor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="reconstruct_relative_bearings",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_boundary_and_airspace_timing",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="operational_sensor_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="test_fusion_interpolation",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="independent_verifier",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_unretained_secondary_feed_gap",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_2",
            statement=(
                "Operational records establish a shared incident window, but no "
                "single continuous trajectory satisfies the retained bearing, "
                "plot, testimony, and Boundary Array constraints."
            ),
            evidence_ids=(
                "controller_voice_log",
                "pilot_debrief",
                "transponder_extract",
                "fused_track_display",
                "primary_radar_plot_extract",
            ),
            tested_ordinary_explanation_ids=("track_fusion_interpolation",),
            preserved_contradiction_ids=("trajectory_solution_divergence",),
            documented_information_gap_ids=("unretained_secondary_sensor_data",),
            confidence="moderate",
            next_collection=(
                "Recover the missing secondary-sensor source or an equivalent "
                "independent record before assigning a physical trajectory."
            ),
            minority_view=(
                "Additional unrecorded operational processing may account for "
                "more of the disagreement than the retained replay demonstrates."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_2",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_2",
        ),
    )


def _complete_archive_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != "aerial_phenomena_archive":
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id="aerial_phenomena_archive",
                ),
            )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="records_custodian",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="case_accession_register",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="audit_case_accessions",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="historical_airspace_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_historical_airspace_records",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="witness_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="witness_drawing_folio",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="analyze_witness_drawings",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="terminology_historian",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="terminology_crosswalk",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="normalize_archive_terminology",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="provenance_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="reconstruct_source_dependencies",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="source_dependency_graph",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="recurrence_cartographer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="build_recurrence_sampling_matrix",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="recurrence_sampling_matrix",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_historical_and_current_constraints",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="provenance_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="test_copying_and_selection_bias",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="archive_independent_reviewer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_missing_original_material_gap",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_3",
            statement=(
                "Dependency-weighted historical cases recur as distributed "
                "boundary constraints, while their drawings, terminology, and "
                "apparent forms do not support one stable object description."
            ),
            evidence_ids=(
                "case_accession_register",
                "witness_drawing_folio",
                "historical_airspace_extract",
                "terminology_crosswalk",
                "source_dependency_graph",
                "recurrence_sampling_matrix",
            ),
            tested_ordinary_explanation_ids=("documentary_copying_selection_bias",),
            preserved_contradiction_ids=("geometric_recurrence_description_divergence",),
            documented_information_gap_ids=("missing_original_case_material",),
            confidence="moderate",
            next_collection=(
                "Seek original media and independently retained operational "
                "records for the highest-weight historical constraints."
            ),
            minority_view=(
                "Selection and unknown dependency may still account for more of "
                "the apparent distributed pattern than the surviving archive shows."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_3",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_3",
        ),
    )


def _complete_holography_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != "holography_laboratory":
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id="holography_laboratory",
                ),
            )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="optical_systems_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="calibration_interferogram_set",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_calibration_interferograms",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="phase_registration_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="registration_reference_grid",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="validate_registration_reference_grid",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="independent_reconstruction_reviewer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="reconstruction_method_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="audit_reconstruction_method",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="constraint_integration_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="register_cross_location_constraints",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="phase_registered_constraint_field",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="reconstruction_technician",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="reconstruct_absent_volume",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="absent_volume_reconstruction",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="artifact_validation_specialist",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="test_inverse_reconstruction_artifacts",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="reconstruction_artifact_sensitivity_report",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="independent_reconstruction_reviewer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_reconstruction_families",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="phase_registration_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_incomplete_phase_coverage",
        ),
    )

    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_4",
            statement=(
                "The registered constraints support a stable boundary-like "
                "absence while leaving the interior model-dependent."
            ),
            evidence_ids=(
                "calibration_interferogram_set",
                "registration_reference_grid",
                "reconstruction_method_record",
                "phase_registered_constraint_field",
                "absent_volume_reconstruction",
                "reconstruction_artifact_sensitivity_report",
            ),
            tested_ordinary_explanation_ids=("inverse_reconstruction_artifact",),
            preserved_contradiction_ids=("stable_boundary_indeterminate_interior",),
            documented_information_gap_ids=("incomplete_angular_phase_coverage",),
            confidence="moderate",
            next_collection=(
                "Collect synchronized observations from unsampled angles with "
                "retained raw phase and timing metadata."
            ),
            minority_view=(
                "Unknown shared processing errors could account for some "
                "features that survive the tested artifact families."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_4",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_4",
        ),
    )


def _complete_subsurface_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != "subsurface_resonance_station":
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id="subsurface_resonance_station",
                ),
            )

    steps = (
        (
            "seismic_array_analyst",
            "seismic_array_waveform_set",
            "inspect_seismic_waveforms",
        ),
        (
            "borehole_acoustics_analyst",
            "borehole_acoustic_record",
            "inspect_borehole_acoustics",
        ),
        (
            "geological_context_specialist",
            "geological_coupling_map",
            "audit_geological_coupling_map",
        ),
        (
            "electromagnetic_coupling_auditor",
            "electromagnetic_background_survey",
            "survey_electromagnetic_background",
        ),
    )
    for role_id, evidence_id, action_id in steps:
        stream = _accept(
            pack,
            stream,
            V2AssignRoleCommand(
                player_id="player_a",
                role_id=role_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ExamineEvidenceCommand(
                player_id="player_a",
                evidence_id=evidence_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2PerformActionCommand(
                player_id="player_a",
                action_id=action_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ReleaseRoleCommand(player_id="player_a"),
        )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="hydrogeology_infrastructure_examiner",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="map_groundwater_and_infrastructure",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="infrastructure_groundwater_exclusion_report",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="distributed_mode_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="build_cross_domain_coherence_model",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="cross_domain_coherence_model",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="independent_geophysical_reviewer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id=("test_local_coupling_and_infrastructure_resonance"),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="regional_mode_sensitivity_report",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="distributed_mode_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_regional_mode_models",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="geological_context_specialist",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_sparse_multiphysics_coverage",
        ),
    )

    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_5",
            statement=(
                "The local records support a regional multiphysics response "
                "without resolving a unique source point or underground object."
            ),
            evidence_ids=(
                "seismic_array_waveform_set",
                "borehole_acoustic_record",
                "geological_coupling_map",
                "electromagnetic_background_survey",
                "infrastructure_groundwater_exclusion_report",
                "cross_domain_coherence_model",
                "regional_mode_sensitivity_report",
            ),
            tested_ordinary_explanation_ids=("local_geology_infrastructure_coupling",),
            preserved_contradiction_ids=("regional_coherence_without_unique_source_volume",),
            documented_information_gap_ids=("sparse_subsurface_multiphysics_coverage",),
            confidence="moderate",
            next_collection=(
                "Add dense peripheral stations, boreholes, conductivity "
                "profiles, groundwater controls, and complete infrastructure logs."
            ),
            minority_view=(
                "Unrecorded shared forcing or multiple ordinary sources may "
                "account for the remaining coherence."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_5",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_5",
        ),
    )


def _complete_quantum_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    assert stream.state.current_position_id == "quantum_state"

    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != "quantum_state_institute":
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id="quantum_state_institute",
                ),
            )

    entry_steps = (
        (
            "measurement_basis_analyst",
            "measurement_basis_registry",
            "inspect_measurement_basis_registry",
        ),
        (
            "state_preparation_operator",
            "state_preparation_protocol",
            "audit_state_preparation_protocol",
        ),
        (
            "cross_location_synthesis_analyst",
            "synchronized_observable_dataset",
            "inspect_synchronized_observable_dataset",
        ),
        (
            "readout_calibration_auditor",
            "readout_calibration_record",
            "audit_readout_calibration",
        ),
    )
    for role_id, evidence_id, action_id in entry_steps:
        stream = _accept(
            pack,
            stream,
            V2AssignRoleCommand(
                player_id="player_a",
                role_id=role_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ExamineEvidenceCommand(
                player_id="player_a",
                evidence_id=evidence_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2PerformActionCommand(
                player_id="player_a",
                action_id=action_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ReleaseRoleCommand(player_id="player_a"),
        )

    derived_steps = (
        (
            "measurement_basis_analyst",
            "compare_incompatible_measurement_bases",
            "basis_compatibility_report",
        ),
        (
            "tomography_estimator",
            "estimate_effective_density_matrix",
            "effective_density_matrix_estimate",
        ),
        (
            "independent_state_reviewer",
            "test_basis_selection_and_regularization",
            "observer_basis_sensitivity_report",
        ),
        (
            "cross_location_synthesis_analyst",
            "reconstruct_interior_viewpoint",
            "interior_viewpoint_reconstruction",
        ),
    )
    for role_id, action_id, evidence_id in derived_steps:
        stream = _accept(
            pack,
            stream,
            V2AssignRoleCommand(
                player_id="player_a",
                role_id=role_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2PerformActionCommand(
                player_id="player_a",
                action_id=action_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ExamineEvidenceCommand(
                player_id="player_a",
                evidence_id=evidence_id,
            ),
        )
        stream = _accept(
            pack,
            stream,
            V2ReleaseRoleCommand(player_id="player_a"),
        )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="measurement_ethics_reviewer",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_exterior_and_interior_descriptions",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="uncertainty_quantification_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id=("document_unmeasured_bases_and_transient_observer_gap"),
        ),
    )

    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id="assessment_6",
            statement=(
                "The synchronized six-facility network supports an effective "
                "state in which the external boundary and regional mode admit "
                "a temporary interior-facing relation. This is a "
                "model-supported viewpoint, not proof of a craft, agency, "
                "consciousness, persistent hidden world, or literal "
                "macroscopic quantum state."
            ),
            evidence_ids=(
                "measurement_basis_registry",
                "state_preparation_protocol",
                "synchronized_observable_dataset",
                "readout_calibration_record",
                "basis_compatibility_report",
                "effective_density_matrix_estimate",
                "observer_basis_sensitivity_report",
                "interior_viewpoint_reconstruction",
            ),
            tested_ordinary_explanation_ids=("basis_selection_regularization_artifact",),
            preserved_contradiction_ids=("exterior_boundary_interior_viewpoint_duality",),
            documented_information_gap_ids=("unmeasured_bases_transient_observer",),
            confidence="moderate",
            next_collection=(
                "Repeat the synchronized preparation with independent basis "
                "families, unsynchronized controls, alternate observer "
                "conventions, and persistence tests."
            ),
            minority_view=(
                "The interior-facing relation may remain a stable artifact of "
                "basis design, correlated inputs, and regularized inversion."
            ),
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="assessment_6",
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_6",
        ),
    )


def _complete_current_position(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    *,
    step_index: int,
) -> V2InvestigationStream:
    if step_index == 0 and stream.state.current_position_id == "network_orientation":
        stream = _accept(
            pack,
            stream,
            V2BeginInvestigationCommand(player_id="player_a"),
        )
    if step_index == 0:
        return _complete_boundary_position(pack, stream)
    if step_index == 1:
        return _complete_aeronautical_position(pack, stream)
    if step_index == 2:
        return _complete_archive_position(pack, stream)
    if step_index == 3:
        return _complete_holography_position(pack, stream)
    if step_index == 4:
        return _complete_subsurface_position(pack, stream)
    if step_index == 5:
        return _complete_quantum_position(pack, stream)

    (
        position_id,
        location_id,
        role_id,
        evidence_id,
        action_id,
        _next_position_id,
        _next_location_id,
        _next_evidence_id,
    ) = POSITION_STEPS[step_index]

    assert stream.state.current_position_id == position_id

    for player_id in ("player_a", "player_b"):
        player = stream.state.get_player(player_id)
        assert player is not None
        if player.current_location_id != location_id:
            stream = _accept(
                pack,
                stream,
                V2MovePlayerCommand(
                    player_id=player_id,
                    location_id=location_id,
                ),
            )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id=role_id,
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id=evidence_id,
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id=action_id,
        ),
    )

    assessment_id = f"assessment_{step_index + 1}"
    stream = _accept(
        pack,
        stream,
        V2DraftAssessmentCommand(
            player_id="player_a",
            assessment_id=assessment_id,
            statement=f"Skeleton assessment for {position_id}.",
            evidence_ids=(evidence_id,),
            confidence="moderate",
            next_collection="Continue to the next institutional method.",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id=assessment_id,
        ),
    )
    return _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id=assessment_id,
        ),
    )


def test_canonical_pack_defines_six_persistent_institutions() -> None:
    pack = load_missing_interior_pack()

    assert tuple(location.id for location in pack.locations) == (
        "boundary_array",
        "aeronautical_incident_center",
        "aerial_phenomena_archive",
        "holography_laboratory",
        "subsurface_resonance_station",
        "quantum_state_institute",
    )
    assert tuple(position.ordinal for position in pack.positions) == (
        0,
        1,
        2,
        3,
        4,
        5,
        6,
    )


def test_canonical_position_chain_is_linear_and_explicit() -> None:
    pack = load_missing_interior_pack()

    assert tuple((position.id, position.next_position_id) for position in pack.positions) == (
        ("network_orientation", "boundary_event"),
        *((step[0], step[5]) for step in POSITION_STEPS),
    )


def test_initial_state_exposes_only_boundary_entry_material() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="canonical_initial",
    )

    assert stream.state.current_position_id == "network_orientation"
    assert stream.state.available_location_ids == {
        location.id for location in pack.locations
    }
    assert stream.state.available_evidence_ids == set()

    stream = _accept(
        pack,
        stream,
        V2BeginInvestigationCommand(player_id="player_a"),
    )
    assert stream.state.current_position_id == "boundary_event"
    assert stream.state.available_evidence_ids == {
        "optical_record",
        "radio_return",
    }


def test_position_completion_unlocks_next_location_and_evidence() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="canonical_progression",
    )

    stream = _complete_current_position(pack, stream, step_index=0)
    event = stream.events[-1]

    assert isinstance(event, V2PositionCompletedEvent)
    assert event.position_id == "boundary_event"
    assert event.next_position_id == "aeronautical_incident"
    assert event.unlocked_location_ids == set()
    assert event.unlocked_evidence_ids == {
        "controller_voice_log",
        "pilot_debrief",
        "transponder_extract",
        "fused_track_display",
    }
    assert deserialize_event(serialize_event(event)) == event

    assert stream.state.current_position_id == "aeronautical_incident"
    assert stream.state.available_location_ids == {
        location.id for location in pack.locations
    }
    assert stream.state.available_evidence_ids == {
        "optical_record",
        "radio_return",
        "receiver_diagnostic",
        "weather_record",
        "controller_voice_log",
        "pilot_debrief",
        "transponder_extract",
        "fused_track_display",
    }

    player = stream.state.get_player("player_a")
    assert player is not None
    assert player.active_role_id is None
    assert replay_events(stream.events) == stream.state


def test_all_six_positions_progress_without_discarding_prior_locations() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="canonical_full_progression",
    )

    for step_index in range(len(POSITION_STEPS)):
        stream = _complete_current_position(
            pack,
            stream,
            step_index=step_index,
        )

    assert stream.state.current_position_id == "quantum_state"
    assert stream.state.completed_position_ids == {
        "network_orientation",
        *(step[0] for step in POSITION_STEPS),
    }
    assert stream.state.available_location_ids == {location.id for location in pack.locations}
    assert stream.state.available_evidence_ids == {source.id for source in pack.evidence_sources}
    assert replay_events(stream.events) == stream.state

    final_event = stream.events[-1]
    assert isinstance(final_event, V2PositionCompletedEvent)
    assert final_event.next_position_id is None
    assert final_event.unlocked_location_ids == set()
    assert final_event.unlocked_evidence_ids == set()


def test_pack_rejects_cyclic_position_progression() -> None:
    payload = _payload()
    payload["positions"][-1]["next_position_id"] = "boundary_event"

    with pytest.raises(ValidationError, match="cyclic position progression"):
        V2InvestigationPack.model_validate(payload)


def test_pack_rejects_unknown_entry_evidence() -> None:
    payload = _payload()
    payload["positions"][1]["available_evidence_ids_on_entry"] = ["missing_evidence"]

    with pytest.raises(ValidationError, match="unknown evidence on entry"):
        V2InvestigationPack.model_validate(payload)


def test_prior_position_assessment_cannot_complete_later_position() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="canonical_assessment_scope",
    )
    stream = _complete_current_position(pack, stream, step_index=0)

    for player_id in ("player_a", "player_b"):
        stream = _accept(
            pack,
            stream,
            V2MovePlayerCommand(
                player_id=player_id,
                location_id="aeronautical_incident_center",
            ),
        )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="controller_records_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="controller_voice_log",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="review_controller_voice_log",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="pilot_testimony_analyst",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="pilot_debrief",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="review_pilot_debrief",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="navigation_records_examiner",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="transponder_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_transponder_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="operational_sensor_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="fused_track_display",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="request_primary_radar_plot",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="primary_radar_plot_extract",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="fusion_processing_record",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="audit_fusion_processing",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="incident_reconstructor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="reconstruct_relative_bearings",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="compare_boundary_and_airspace_timing",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="operational_sensor_auditor",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="test_fusion_interpolation",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    stream = _accept(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="independent_verifier",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="document_unretained_secondary_feed_gap",
        ),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="assessment_1",
        ),
    )

    assert result.accepted is False
    assert result.code == "assessment_missing_explanations"
    assert result.stream is stream
