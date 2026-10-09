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

ARCHIVE_ROLE_IDS = {
    "records_custodian",
    "witness_analyst",
    "terminology_historian",
    "provenance_auditor",
    "recurrence_cartographer",
    "archive_independent_reviewer",
}
ARCHIVE_INSTRUMENT_IDS = {
    "archive_provenance_index",
    "document_imaging_station",
    "case_normalization_workbench",
}
ARCHIVE_ENTRY_EVIDENCE_IDS = {
    "case_accession_register",
    "witness_drawing_folio",
    "historical_airspace_extract",
    "terminology_crosswalk",
}
ARCHIVE_DERIVED_EVIDENCE_IDS = {
    "source_dependency_graph",
    "recurrence_sampling_matrix",
}
ARCHIVE_EVIDENCE_IDS = ARCHIVE_ENTRY_EVIDENCE_IDS | ARCHIVE_DERIVED_EVIDENCE_IDS
ARCHIVE_ACTION_IDS = {
    "audit_case_accessions",
    "analyze_witness_drawings",
    "inspect_historical_airspace_records",
    "normalize_archive_terminology",
    "reconstruct_source_dependencies",
    "build_recurrence_sampling_matrix",
    "compare_historical_and_current_constraints",
    "test_copying_and_selection_bias",
    "document_missing_original_material_gap",
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


def _archive_start_stream(
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
        "receiver_diagnostic",
        "weather_record",
        "controller_voice_log",
        "pilot_debrief",
        "transponder_extract",
        "fused_track_display",
        "primary_radar_plot_extract",
        "fusion_processing_record",
    }
    updated_state = replace(
        stream.state,
        current_position_id="archive_convergence",
        available_location_ids=frozenset(
            {
                "boundary_array",
                "aeronautical_incident_center",
                "aerial_phenomena_archive",
            }
        ),
        players=tuple(
            replace(
                player,
                current_location_id="aerial_phenomena_archive",
                active_role_id=None,
            )
            for player in stream.state.players
        ),
        available_evidence_ids=frozenset(earlier_evidence | ARCHIVE_ENTRY_EVIDENCE_IDS),
        examined_evidence_ids=frozenset(
            {
                "optical_record",
                "primary_radar_plot_extract",
            }
        ),
        completed_position_ids=frozenset({"boundary_event", "aeronautical_incident"}),
    )
    return replace(stream, state=updated_state)


def _perform_archive_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "records_custodian")
    stream = _examine(pack, stream, "case_accession_register")
    stream = _act(pack, stream, "audit_case_accessions")
    stream = _examine(pack, stream, "historical_airspace_extract")
    stream = _act(pack, stream, "inspect_historical_airspace_records")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "witness_analyst")
    stream = _examine(pack, stream, "witness_drawing_folio")
    stream = _act(pack, stream, "analyze_witness_drawings")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "terminology_historian")
    stream = _examine(pack, stream, "terminology_crosswalk")
    stream = _act(pack, stream, "normalize_archive_terminology")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "provenance_auditor")
    stream = _act(pack, stream, "reconstruct_source_dependencies")
    stream = _examine(pack, stream, "source_dependency_graph")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "recurrence_cartographer")
    stream = _act(pack, stream, "build_recurrence_sampling_matrix")
    stream = _examine(pack, stream, "recurrence_sampling_matrix")
    stream = _act(pack, stream, "compare_historical_and_current_constraints")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "provenance_auditor")
    stream = _act(pack, stream, "test_copying_and_selection_bias")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "archive_independent_reviewer")
    return _act(pack, stream, "document_missing_original_material_gap")


def _draft_confirmed_archive_assessment(
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
                "Dependency-weighted cases recur as distributed boundary "
                "constraints without converging on one stable object description."
            ),
            evidence_ids=evidence_ids,
            tested_ordinary_explanation_ids=("documentary_copying_selection_bias",),
            preserved_contradiction_ids=("geometric_recurrence_description_divergence",),
            documented_information_gap_ids=("missing_original_case_material",),
            confidence="moderate",
            next_collection=(
                "Recover original media and independently retained operational "
                "records for the highest-weight cases."
            ),
            minority_view=(
                "Unknown dependence and archival selection may explain more of "
                "the recurrence than the surviving records reveal."
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


def test_archive_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[3]

    assert pack.pack.content_version == "0.10.0"
    assert position.id == "archive_convergence"
    assert position.title == "A Pattern Without a Common Cause"
    assert set(position.available_evidence_ids_on_entry) == (ARCHIVE_ENTRY_EVIDENCE_IDS)
    assert position.completion.minimum_examined_source_classes == 6
    assert set(position.completion.required_completed_action_ids) == (ARCHIVE_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "documentary_copying_selection_bias",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "geometric_recurrence_description_divergence",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "missing_original_case_material",
    )


def test_archive_has_distinct_roles_and_record_workstations() -> None:
    pack = load_missing_interior_pack()

    roles = {
        role.id for role in pack.roles if role.allowed_location_ids == ("aerial_phenomena_archive",)
    }
    instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "aerial_phenomena_archive"
    }

    assert roles == ARCHIVE_ROLE_IDS
    assert instruments == ARCHIVE_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in ARCHIVE_ROLE_IDS)


def test_archive_sources_preserve_record_level_and_dependence() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    accession = sources["case_accession_register"]
    drawings = sources["witness_drawing_folio"]
    airspace = sources["historical_airspace_extract"]
    terminology = sources["terminology_crosswalk"]
    graph = sources["source_dependency_graph"]
    matrix = sources["recurrence_sampling_matrix"]

    assert accession.raw_or_derived == "processed"
    assert drawings.raw_or_derived == "testimony"
    assert airspace.raw_or_derived == "processed"
    assert terminology.raw_or_derived == "summary"
    assert graph.raw_or_derived == "derived"
    assert matrix.raw_or_derived == "derived"
    assert (
        len(
            {
                source.source_class
                for source in sources.values()
                if source.id in ARCHIVE_EVIDENCE_IDS
            }
        )
        == 6
    )
    assert graph.independence_group != matrix.independence_group
    assert "Proof that every unlinked source is independent" in graph.unsupported_extrapolations
    assert "Proof that every case has a common cause" in matrix.unsupported_extrapolations


def test_archive_entry_excludes_dependency_and_recurrence_products() -> None:
    pack = load_missing_interior_pack()
    stream = _archive_start_stream(pack, stream_id="archive_entry_sources")

    assert ARCHIVE_ENTRY_EVIDENCE_IDS <= stream.state.available_evidence_ids
    assert ARCHIVE_DERIVED_EVIDENCE_IDS.isdisjoint(stream.state.available_evidence_ids)


def test_dependency_and_recurrence_actions_unlock_derived_sources_in_order() -> None:
    pack = load_missing_interior_pack()
    stream = _archive_start_stream(pack, stream_id="archive_unlock_order")

    stream = _assign(pack, stream, "records_custodian")
    stream = _examine(pack, stream, "case_accession_register")
    stream = _act(pack, stream, "audit_case_accessions")
    stream = _examine(pack, stream, "historical_airspace_extract")
    stream = _act(pack, stream, "inspect_historical_airspace_records")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "witness_analyst")
    stream = _examine(pack, stream, "witness_drawing_folio")
    stream = _act(pack, stream, "analyze_witness_drawings")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "terminology_historian")
    stream = _examine(pack, stream, "terminology_crosswalk")
    stream = _act(pack, stream, "normalize_archive_terminology")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "provenance_auditor")
    stream = _act(pack, stream, "reconstruct_source_dependencies")

    assert "source_dependency_graph" in stream.state.available_evidence_ids
    assert "recurrence_sampling_matrix" not in stream.state.available_evidence_ids

    stream = _examine(pack, stream, "source_dependency_graph")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "recurrence_cartographer")
    stream = _act(pack, stream, "build_recurrence_sampling_matrix")

    assert "recurrence_sampling_matrix" in stream.state.available_evidence_ids


def test_archive_actions_preserve_explanation_conflict_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = _archive_start_stream(pack, stream_id="archive_effects")
    stream = _perform_archive_investigation(pack, stream)

    assert ARCHIVE_ACTION_IDS <= stream.state.completed_action_ids
    assert "documentary_copying_selection_bias" in (stream.state.tested_ordinary_explanation_ids)
    assert "geometric_recurrence_description_divergence" in (
        stream.state.preserved_contradiction_ids
    )
    assert "missing_original_case_material" in (stream.state.documented_information_gap_ids)


def test_recurrence_matrix_alone_cannot_complete_archive_position() -> None:
    pack = load_missing_interior_pack()
    stream = _archive_start_stream(pack, stream_id="archive_source_class_gate")
    stream = _perform_archive_investigation(pack, stream)
    stream = _draft_confirmed_archive_assessment(
        pack,
        stream,
        assessment_id="matrix_only",
        evidence_ids=("case_accession_register", "recurrence_sampling_matrix"),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="matrix_only",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_confirmed_all_source_assessment_unlocks_holography_position() -> None:
    pack = load_missing_interior_pack()
    stream = _archive_start_stream(pack, stream_id="archive_completion")
    stream = _perform_archive_investigation(pack, stream)
    stream = _draft_confirmed_archive_assessment(
        pack,
        stream,
        assessment_id="archive_assessment",
        evidence_ids=(
            "case_accession_register",
            "witness_drawing_folio",
            "historical_airspace_extract",
            "terminology_crosswalk",
            "source_dependency_graph",
            "recurrence_sampling_matrix",
        ),
    )
    stream = _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="archive_assessment",
        ),
    )

    assert stream.state.current_position_id == "holographic_reconstruction"
    assert "holography_laboratory" in stream.state.available_location_ids
    assert {
        "calibration_interferogram_set",
        "registration_reference_grid",
        "reconstruction_method_record",
    } <= stream.state.available_evidence_ids


def test_archive_comparison_requires_current_boundary_and_aviation_records() -> None:
    pack = load_missing_interior_pack()
    action = next(
        item for item in pack.actions if item.id == "compare_historical_and_current_constraints"
    )

    assert {
        "optical_record",
        "primary_radar_plot_extract",
        "historical_airspace_extract",
        "recurrence_sampling_matrix",
    } <= set(action.prerequisites.required_examined_evidence_ids)
    assert action.location_id == "aerial_phenomena_archive"


def test_archive_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    content = [
        pack.locations[2].description,
        pack.positions[2].title,
    ]
    content.extend(role.description for role in pack.roles if role.id in ARCHIVE_ROLE_IDS)
    content.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in ARCHIVE_INSTRUMENT_IDS
    )
    content.extend(
        source.provenance for source in pack.evidence_sources if source.id in ARCHIVE_EVIDENCE_IDS
    )
    content.extend(action.description for action in pack.actions if action.id in ARCHIVE_ACTION_IDS)

    assert all("skeleton" not in item.casefold() for item in content)
