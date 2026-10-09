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
    V2PositionCompletedEvent,
    V2ReleaseRoleCommand,
    execute_command,
    initialize_event_stream,
)

QUANTUM_ROLE_IDS = {
    "state_preparation_operator",
    "measurement_basis_analyst",
    "cross_location_synthesis_analyst",
    "tomography_estimator",
    "readout_calibration_auditor",
    "uncertainty_quantification_analyst",
    "measurement_ethics_reviewer",
    "independent_state_reviewer",
}
QUANTUM_INSTRUMENT_IDS = {
    "measurement_basis_registry_console",
    "distributed_state_preparation_controller",
    "cross_location_observable_assembler",
    "effective_tomography_cluster",
    "readout_calibration_bench",
    "observer_sensitivity_workbench",
}
QUANTUM_ENTRY_EVIDENCE_IDS = {
    "measurement_basis_registry",
    "state_preparation_protocol",
    "synchronized_observable_dataset",
    "readout_calibration_record",
}
QUANTUM_DERIVED_EVIDENCE_IDS = {
    "basis_compatibility_report",
    "effective_density_matrix_estimate",
    "observer_basis_sensitivity_report",
    "interior_viewpoint_reconstruction",
}
QUANTUM_EVIDENCE_IDS = QUANTUM_ENTRY_EVIDENCE_IDS | QUANTUM_DERIVED_EVIDENCE_IDS
QUANTUM_ACTION_IDS = {
    "inspect_measurement_basis_registry",
    "audit_state_preparation_protocol",
    "inspect_synchronized_observable_dataset",
    "audit_readout_calibration",
    "compare_incompatible_measurement_bases",
    "estimate_effective_density_matrix",
    "test_basis_selection_and_regularization",
    "reconstruct_interior_viewpoint",
    "compare_exterior_and_interior_descriptions",
    "document_unmeasured_bases_and_transient_observer_gap",
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


def _quantum_start_stream(
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
        source.id
        for source in pack.evidence_sources
        if source.origin_location_id != "quantum_state_institute"
    }
    updated_state = replace(
        stream.state,
        current_position_id="quantum_state",
        available_location_ids=frozenset(location.id for location in pack.locations),
        players=tuple(
            replace(
                player,
                current_location_id="quantum_state_institute",
                active_role_id=None,
            )
            for player in stream.state.players
        ),
        available_evidence_ids=frozenset(earlier_evidence | QUANTUM_ENTRY_EVIDENCE_IDS),
        examined_evidence_ids=frozenset(earlier_evidence),
        completed_position_ids=frozenset(
            {
                "boundary_event",
                "aeronautical_incident",
                "archive_convergence",
                "holographic_reconstruction",
                "subsurface_resonance",
            }
        ),
    )
    return replace(stream, state=updated_state)


def _perform_entry_audits(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _assign(pack, stream, "measurement_basis_analyst")
    stream = _examine(pack, stream, "measurement_basis_registry")
    stream = _act(pack, stream, "inspect_measurement_basis_registry")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "state_preparation_operator")
    stream = _examine(pack, stream, "state_preparation_protocol")
    stream = _act(pack, stream, "audit_state_preparation_protocol")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "cross_location_synthesis_analyst")
    stream = _examine(pack, stream, "synchronized_observable_dataset")
    stream = _act(pack, stream, "inspect_synchronized_observable_dataset")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "readout_calibration_auditor")
    stream = _examine(pack, stream, "readout_calibration_record")
    stream = _act(pack, stream, "audit_readout_calibration")
    return _release(pack, stream)


def _perform_quantum_investigation(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
) -> V2InvestigationStream:
    stream = _perform_entry_audits(pack, stream)

    stream = _assign(pack, stream, "measurement_basis_analyst")
    stream = _act(pack, stream, "compare_incompatible_measurement_bases")
    stream = _examine(pack, stream, "basis_compatibility_report")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "tomography_estimator")
    stream = _act(pack, stream, "estimate_effective_density_matrix")
    stream = _examine(pack, stream, "effective_density_matrix_estimate")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "independent_state_reviewer")
    stream = _act(pack, stream, "test_basis_selection_and_regularization")
    stream = _examine(pack, stream, "observer_basis_sensitivity_report")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "cross_location_synthesis_analyst")
    stream = _act(pack, stream, "reconstruct_interior_viewpoint")
    stream = _examine(pack, stream, "interior_viewpoint_reconstruction")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "measurement_ethics_reviewer")
    stream = _act(pack, stream, "compare_exterior_and_interior_descriptions")
    stream = _release(pack, stream)

    stream = _assign(pack, stream, "uncertainty_quantification_analyst")
    return _act(
        pack,
        stream,
        "document_unmeasured_bases_and_transient_observer_gap",
    )


def _draft_confirmed_quantum_assessment(
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
                "Across the tested bases, the six-facility network supports an "
                "effective state in which the externally observed boundary and "
                "regional mode admit a temporary interior-facing relation. The "
                "result is a model-supported viewpoint, not proof of a craft, "
                "conscious entity, persistent hidden world, or literal "
                "macroscopic quantum state."
            ),
            evidence_ids=evidence_ids,
            tested_ordinary_explanation_ids=("basis_selection_regularization_artifact",),
            preserved_contradiction_ids=("exterior_boundary_interior_viewpoint_duality",),
            documented_information_gap_ids=("unmeasured_bases_transient_observer",),
            confidence="moderate",
            next_collection=(
                "Repeat the synchronized network preparation with additional "
                "independent basis families, unsynchronized controls, altered "
                "observer conventions, and persistence tests."
            ),
            minority_view=(
                "The interior-facing relation may be a stable artifact of "
                "basis design, correlated inputs, and regularized inversion "
                "rather than a physical observer relation."
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


def test_quantum_position_uses_production_completion_contract() -> None:
    pack = load_missing_interior_pack()
    position = pack.positions[6]

    assert pack.pack.content_version == "0.10.0"
    assert position.id == "quantum_state"
    assert position.title == "The View From the Missing Interior"
    assert set(position.available_evidence_ids_on_entry) == (QUANTUM_ENTRY_EVIDENCE_IDS)
    assert position.completion.minimum_examined_source_classes == 8
    assert set(position.completion.required_completed_action_ids) == (QUANTUM_ACTION_IDS)
    assert position.completion.required_tested_ordinary_explanation_ids == (
        "basis_selection_regularization_artifact",
    )
    assert position.completion.required_preserved_contradiction_ids == (
        "exterior_boundary_interior_viewpoint_duality",
    )
    assert position.completion.required_documented_information_gap_ids == (
        "unmeasured_bases_transient_observer",
    )


def test_quantum_has_distinct_roles_and_state_reconstruction_instruments() -> None:
    pack = load_missing_interior_pack()

    roles = {
        role.id for role in pack.roles if role.allowed_location_ids == ("quantum_state_institute",)
    }
    instruments = {
        instrument.id
        for instrument in pack.instruments
        if instrument.location_id == "quantum_state_institute"
    }

    assert roles == QUANTUM_ROLE_IDS
    assert instruments == QUANTUM_INSTRUMENT_IDS
    assert all(role.scope == "position" for role in pack.roles if role.id in QUANTUM_ROLE_IDS)


def test_quantum_sources_separate_basis_preparation_readout_and_models() -> None:
    pack = load_missing_interior_pack()
    sources = {source.id: source for source in pack.evidence_sources}

    assert sources["measurement_basis_registry"].raw_or_derived == "summary"
    assert sources["state_preparation_protocol"].raw_or_derived == "processed"
    assert sources["synchronized_observable_dataset"].raw_or_derived == "processed"
    assert sources["readout_calibration_record"].raw_or_derived == "raw"
    assert all(
        sources[source_id].raw_or_derived == "derived" for source_id in QUANTUM_DERIVED_EVIDENCE_IDS
    )
    assert len({sources[source_id].source_class for source_id in QUANTUM_EVIDENCE_IDS}) == 8
    assert "A literal quantum density matrix of the regional phenomenon" in (
        sources["effective_density_matrix_estimate"].unsupported_extrapolations
    )
    assert (
        "Proof of consciousness, agency, an inhabited craft, or a persistent hidden world"
        in sources["interior_viewpoint_reconstruction"].unsupported_extrapolations
    )


def test_quantum_entry_excludes_derived_products() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(pack, stream_id="quantum_entry_sources")

    assert QUANTUM_ENTRY_EVIDENCE_IDS <= stream.state.available_evidence_ids
    assert QUANTUM_DERIVED_EVIDENCE_IDS.isdisjoint(stream.state.available_evidence_ids)


def test_quantum_products_unlock_in_basis_state_sensitivity_viewpoint_order() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(pack, stream_id="quantum_unlock_order")
    stream = _perform_entry_audits(pack, stream)

    stream = _assign(pack, stream, "measurement_basis_analyst")
    stream = _act(pack, stream, "compare_incompatible_measurement_bases")

    assert "basis_compatibility_report" in stream.state.available_evidence_ids
    assert "effective_density_matrix_estimate" not in (stream.state.available_evidence_ids)

    stream = _examine(pack, stream, "basis_compatibility_report")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "tomography_estimator")
    stream = _act(pack, stream, "estimate_effective_density_matrix")

    assert "effective_density_matrix_estimate" in (stream.state.available_evidence_ids)
    assert "observer_basis_sensitivity_report" not in (stream.state.available_evidence_ids)
    assert "interior_viewpoint_reconstruction" not in (stream.state.available_evidence_ids)


def test_effective_state_estimate_requires_prior_location_products() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(
        pack,
        stream_id="quantum_cross_location_gate",
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
    stream = _perform_entry_audits(pack, stream)
    stream = _assign(pack, stream, "measurement_basis_analyst")
    stream = _act(pack, stream, "compare_incompatible_measurement_bases")
    stream = _examine(pack, stream, "basis_compatibility_report")
    stream = _release(pack, stream)
    stream = _assign(pack, stream, "tomography_estimator")

    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="estimate_effective_density_matrix",
        ),
    )

    assert result.accepted is False
    assert result.code == "required_evidence_missing"
    assert "recurrence_sampling_matrix" in result.message


def test_quantum_actions_record_control_test_duality_and_gap() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(pack, stream_id="quantum_effects")
    stream = _perform_quantum_investigation(pack, stream)

    assert QUANTUM_ACTION_IDS <= stream.state.completed_action_ids
    assert "basis_selection_regularization_artifact" in (
        stream.state.tested_ordinary_explanation_ids
    )
    assert "exterior_boundary_interior_viewpoint_duality" in (
        stream.state.preserved_contradiction_ids
    )
    assert "unmeasured_bases_transient_observer" in (stream.state.documented_information_gap_ids)


def test_tomography_only_assessment_cannot_complete_position() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(
        pack,
        stream_id="quantum_source_class_gate",
    )
    stream = _perform_quantum_investigation(pack, stream)
    stream = _draft_confirmed_quantum_assessment(
        pack,
        stream,
        assessment_id="tomography_only",
        evidence_ids=(
            "measurement_basis_registry",
            "effective_density_matrix_estimate",
        ),
    )

    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="tomography_only",
        ),
    )

    assert result.accepted is False
    assert result.code == "insufficient_source_classes"
    assert result.stream is stream


def test_confirmed_quantum_assessment_completes_terminal_position() -> None:
    pack = load_missing_interior_pack()
    stream = _quantum_start_stream(pack, stream_id="quantum_completion")
    stream = _perform_quantum_investigation(pack, stream)
    stream = _draft_confirmed_quantum_assessment(
        pack,
        stream,
        assessment_id="quantum_assessment",
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
    )
    stream = _accept(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="quantum_assessment",
        ),
    )

    assert stream.state.current_position_id == "quantum_state"
    assert stream.state.completed_position_ids == {
        "boundary_event",
        "aeronautical_incident",
        "archive_convergence",
        "holographic_reconstruction",
        "subsurface_resonance",
        "quantum_state",
    }
    player = stream.state.get_player("player_a")
    assert player is not None
    assert player.active_role_id is None

    event = stream.events[-1]
    assert isinstance(event, V2PositionCompletedEvent)
    assert event.position_id == "quantum_state"
    assert event.next_position_id is None
    assert event.unlocked_location_ids == set()
    assert event.unlocked_evidence_ids == set()


def test_quantum_production_content_contains_no_skeleton_placeholders() -> None:
    pack = load_missing_interior_pack()

    content = [
        pack.locations[5].description,
        pack.positions[5].title,
    ]
    content.extend(role.description for role in pack.roles if role.id in QUANTUM_ROLE_IDS)
    content.extend(
        instrument.intended_purpose
        for instrument in pack.instruments
        if instrument.id in QUANTUM_INSTRUMENT_IDS
    )
    content.extend(
        source.provenance for source in pack.evidence_sources if source.id in QUANTUM_EVIDENCE_IDS
    )
    content.extend(action.description for action in pack.actions if action.id in QUANTUM_ACTION_IDS)

    assert all("skeleton" not in item.casefold() for item in content)
    assert all(item.id != "boundary_state_analysis" for item in pack.evidence_sources)
    assert all(item.id != "review_state_analysis" for item in pack.actions)
    assert all(item.id != "state_modeler" for item in pack.roles)
    assert all(item.id != "boundary_state_workbench" for item in pack.instruments)
