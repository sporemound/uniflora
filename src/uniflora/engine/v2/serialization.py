from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from uniflora.engine.v2.events import (
    V2ActionPerformedEvent,
    V2ActionProposedEvent,
    V2CapacityPassedEvent,
    V2ProposalSupportedEvent,
    V2AssessmentConfirmedEvent,
    V2AssessmentDraftedEvent,
    V2EvidenceExaminedEvent,
    V2InvestigationEvent,
    V2InvestigationInitializedEvent,
    V2PlayerJoinedEvent,
    V2PlayerMovedEvent,
    V2PositionCompletedEvent,
    V2PromotedFindingRegisteredEvent,
    V2QualityReviewSubmittedEvent,
    V2ReleasedRole,
    V2RoleAssignedEvent,
    V2RoleReleasedEvent,
)
from uniflora.engine.v2.state import (
    V2AdaptationSelectionState,
    V2AssessmentState,
    V2HypothesisState,
    V2InvestigationState,
    V2PlayerState,
    V2PositionQualitySealState,
    V2PromotedFindingState,
    V2QualityReviewState,
    V2ModelProbabilityState,
    V2StochasticDatumState,
    V2StochasticDrawState,
    V2StochasticModelSupportState,
    V2StochasticObservationState,
    V2StochasticProcessState,
    V2StochasticResolutionState,
    V2StrategicBoardState,
    V2StrategicConditionState,
    V2StrategicDriftResolutionState,
    V2StrategicPlayerRoundState,
    V2StrategicPositionOutcomeState,
    V2StrategicProposalState,
    V2StrategicResolutionState,
    V2StrategicResourceState,
    V2StrategicTrackState,
)

V2_EVENT_SCHEMA_VERSION = 3
V2_STATE_SCHEMA_VERSION = 1


class V2SerializationError(ValueError):
    """Raised when canonical v2 data cannot be encoded or decoded."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise V2SerializationError(f"value is not canonical-JSON compatible: {exc}") from exc

    return text.encode("utf-8")


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise V2SerializationError(f"{label} must be a JSON object")

    if not all(isinstance(key, str) for key in value):
        raise V2SerializationError(f"{label} keys must be strings")

    return value


def _require_exact_keys(
    value: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(value)

    if actual == expected:
        return

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []

    if missing:
        details.append("missing " + ", ".join(missing))

    if extra:
        details.append("unexpected " + ", ".join(extra))

    raise V2SerializationError(f"{label} has invalid fields: {'; '.join(details)}")


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V2SerializationError(f"{label} must be a nonblank string")

    return value


def _require_optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None

    return _require_string(value, label=label)


def _require_boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise V2SerializationError(f"{label} must be boolean")
    return value


def _require_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V2SerializationError(f"{label} must be an integer")

    return value


def _require_string_sequence(
    value: object,
    *,
    label: str,
    unique: bool = True,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise V2SerializationError(f"{label} must be a JSON array")

    result = tuple(_require_string(item, label=f"{label} item") for item in value)

    if unique and len(result) != len(set(result)):
        raise V2SerializationError(f"{label} must not contain duplicates")

    return result


def _player_to_record(player: V2PlayerState) -> dict[str, object]:
    record: dict[str, object] = {
        "active_role_id": player.active_role_id,
        "current_location_id": player.current_location_id,
        "player_id": player.player_id,
        "proficiencies": sorted(player.proficiencies),
    }
    if player.active_role_display_name is not None or player.active_role_description is not None:
        record["active_role_display_name"] = player.active_role_display_name
        record["active_role_description"] = player.active_role_description
    return record


def _player_from_record(value: object) -> V2PlayerState:
    record = _require_mapping(value, label="player state")
    base_keys = frozenset(
        {"active_role_id", "current_location_id", "player_id", "proficiencies"}
    )
    custom_keys = frozenset({"active_role_display_name", "active_role_description"})
    has_custom = custom_keys.issubset(record)
    _require_exact_keys(
        record,
        expected=base_keys | (custom_keys if has_custom else frozenset()),
        label="player state",
    )

    return V2PlayerState(
        player_id=_require_string(record["player_id"], label="player ID"),
        current_location_id=_require_string(
            record["current_location_id"],
            label="current location ID",
        ),
        active_role_id=_require_optional_string(
            record["active_role_id"],
            label="active role ID",
        ),
        active_role_display_name=(
            _require_optional_string(
                record["active_role_display_name"], label="active role display name"
            )
            if has_custom
            else None
        ),
        active_role_description=(
            _require_optional_string(
                record["active_role_description"], label="active role description"
            )
            if has_custom
            else None
        ),
        proficiencies=frozenset(
            _require_string_sequence(
                record["proficiencies"],
                label="proficiencies",
            )
        ),
    )


def _hypothesis_to_record(hypothesis: V2HypothesisState) -> dict[str, object]:
    return {
        "author_player_id": hypothesis.author_player_id,
        "id": hypothesis.id,
        "statement": hypothesis.statement,
        "status": hypothesis.status,
    }


def _hypothesis_from_record(value: object) -> V2HypothesisState:
    record = _require_mapping(value, label="hypothesis state")
    _require_exact_keys(
        record,
        expected=frozenset({"author_player_id", "id", "statement", "status"}),
        label="hypothesis state",
    )
    status = _require_string(record["status"], label="hypothesis status")

    if status not in {"registered", "under_test", "retained", "unsupported"}:
        raise V2SerializationError(f"unsupported hypothesis status: {status!r}")

    return V2HypothesisState(
        id=_require_string(record["id"], label="hypothesis ID"),
        author_player_id=_require_string(
            record["author_player_id"],
            label="hypothesis author player ID",
        ),
        statement=_require_string(
            record["statement"],
            label="hypothesis statement",
        ),
        status=cast(
            Literal["registered", "under_test", "retained", "unsupported"],
            status,
        ),
    )


def assessment_to_record(assessment: V2AssessmentState) -> dict[str, object]:
    return {
        "author_player_id": assessment.author_player_id,
        "confidence": assessment.confidence,
        "confirmed_by_player_ids": sorted(assessment.confirmed_by_player_ids),
        "documented_information_gap_ids": sorted(assessment.documented_information_gap_ids),
        "evidence_ids": sorted(assessment.evidence_ids),
        "id": assessment.id,
        "minority_view": assessment.minority_view,
        "next_collection": assessment.next_collection,
        "preserved_contradiction_ids": sorted(assessment.preserved_contradiction_ids),
        "statement": assessment.statement,
        "status": assessment.status,
        "tested_ordinary_explanation_ids": sorted(assessment.tested_ordinary_explanation_ids),
    }


def assessment_from_record(value: object) -> V2AssessmentState:
    record = _require_mapping(value, label="assessment state")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "author_player_id",
                "confidence",
                "confirmed_by_player_ids",
                "documented_information_gap_ids",
                "evidence_ids",
                "id",
                "minority_view",
                "next_collection",
                "preserved_contradiction_ids",
                "statement",
                "status",
                "tested_ordinary_explanation_ids",
            }
        ),
        label="assessment state",
    )
    confidence = _require_string(record["confidence"], label="assessment confidence")
    status = _require_string(record["status"], label="assessment status")

    if confidence not in {"low", "moderate", "high"}:
        raise V2SerializationError(f"unsupported assessment confidence: {confidence!r}")

    if status not in {"draft", "confirmed"}:
        raise V2SerializationError(f"unsupported assessment status: {status!r}")

    return V2AssessmentState(
        id=_require_string(record["id"], label="assessment ID"),
        author_player_id=_require_string(
            record["author_player_id"],
            label="assessment author player ID",
        ),
        statement=_require_string(
            record["statement"],
            label="assessment statement",
        ),
        evidence_ids=frozenset(
            _require_string_sequence(
                record["evidence_ids"],
                label="assessment evidence IDs",
            )
        ),
        tested_ordinary_explanation_ids=frozenset(
            _require_string_sequence(
                record["tested_ordinary_explanation_ids"],
                label="assessment tested ordinary explanation IDs",
            )
        ),
        preserved_contradiction_ids=frozenset(
            _require_string_sequence(
                record["preserved_contradiction_ids"],
                label="assessment preserved contradiction IDs",
            )
        ),
        documented_information_gap_ids=frozenset(
            _require_string_sequence(
                record["documented_information_gap_ids"],
                label="assessment documented information gap IDs",
            )
        ),
        confidence=cast(Literal["low", "moderate", "high"], confidence),
        next_collection=_require_string(
            record["next_collection"],
            label="assessment next collection",
        ),
        minority_view=_require_optional_string(
            record["minority_view"],
            label="assessment minority view",
        ),
        status=cast(Literal["draft", "confirmed"], status),
        confirmed_by_player_ids=frozenset(
            _require_string_sequence(
                record["confirmed_by_player_ids"],
                label="assessment confirming player IDs",
            )
        ),
    )


def _promoted_finding_to_record(finding: V2PromotedFindingState) -> dict[str, object]:
    return {
        "author_player_id": finding.author_player_id,
        "finding_id": finding.finding_id,
        "position_id": finding.position_id,
        "revision": finding.revision,
    }


def _promoted_finding_from_record(value: object) -> V2PromotedFindingState:
    record = _require_mapping(value, label="promoted finding")
    _require_exact_keys(
        record,
        expected=frozenset({"author_player_id", "finding_id", "position_id", "revision"}),
        label="promoted finding",
    )
    return V2PromotedFindingState(
        finding_id=_require_string(record["finding_id"], label="finding ID"),
        revision=_require_integer(record["revision"], label="finding revision"),
        position_id=_require_string(record["position_id"], label="finding position ID"),
        author_player_id=_require_string(
            record["author_player_id"], label="finding author player ID"
        ),
    )


def _quality_review_to_record(review: V2QualityReviewState) -> dict[str, object]:
    return {
        "author_player_id": review.author_player_id,
        "confidence_calibration": review.confidence_calibration,
        "contradictions_preserved": review.contradictions_preserved,
        "evidence_support": review.evidence_support,
        "ordinary_alternatives": review.ordinary_alternatives,
        "position_id": review.position_id,
        "rationale": review.rationale,
        "reproducibility": review.reproducibility,
        "reviewer_player_id": review.reviewer_player_id,
        "subject_id": review.subject_id,
        "subject_kind": review.subject_kind,
        "subject_revision": review.subject_revision,
    }


def _quality_review_from_record(value: object) -> V2QualityReviewState:
    record = _require_mapping(value, label="quality review")
    expected = frozenset(
        {
            "author_player_id",
            "confidence_calibration",
            "contradictions_preserved",
            "evidence_support",
            "ordinary_alternatives",
            "position_id",
            "rationale",
            "reproducibility",
            "reviewer_player_id",
            "subject_id",
            "subject_kind",
            "subject_revision",
        }
    )
    _require_exact_keys(record, expected=expected, label="quality review")
    subject_kind = _require_string(record["subject_kind"], label="review subject kind")
    if subject_kind not in {"finding", "assessment"}:
        raise V2SerializationError(f"unsupported review subject kind: {subject_kind!r}")
    return V2QualityReviewState(
        subject_kind=cast(Literal["finding", "assessment"], subject_kind),
        subject_id=_require_string(record["subject_id"], label="review subject ID"),
        subject_revision=_require_integer(
            record["subject_revision"], label="review subject revision"
        ),
        position_id=_require_string(record["position_id"], label="review position ID"),
        author_player_id=_require_string(
            record["author_player_id"], label="review subject author player ID"
        ),
        reviewer_player_id=_require_string(
            record["reviewer_player_id"], label="reviewer player ID"
        ),
        evidence_support=_require_integer(
            record["evidence_support"], label="evidence-support score"
        ),
        ordinary_alternatives=_require_integer(
            record["ordinary_alternatives"], label="ordinary-alternatives score"
        ),
        contradictions_preserved=_require_integer(
            record["contradictions_preserved"], label="contradictions-preserved score"
        ),
        confidence_calibration=_require_integer(
            record["confidence_calibration"], label="confidence-calibration score"
        ),
        reproducibility=_require_integer(record["reproducibility"], label="reproducibility score"),
        rationale=_require_string(record["rationale"], label="review rationale"),
    )


def _quality_seal_to_record(seal: V2PositionQualitySealState) -> dict[str, object]:
    return {
        "baseline_fallback": seal.baseline_fallback,
        "position_id": seal.position_id,
        "position_ordinal": seal.position_ordinal,
        "reviewed_subject_count": seal.reviewed_subject_count,
        "score_denominator": seal.score_denominator,
        "score_numerator": seal.score_numerator,
    }


def _quality_seal_from_record(value: object) -> V2PositionQualitySealState:
    record = _require_mapping(value, label="position quality seal")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "baseline_fallback",
                "position_id",
                "position_ordinal",
                "reviewed_subject_count",
                "score_denominator",
                "score_numerator",
            }
        ),
        label="position quality seal",
    )
    fallback = record["baseline_fallback"]
    if not isinstance(fallback, bool):
        raise V2SerializationError("baseline fallback must be a boolean")
    numerator = record["score_numerator"]
    denominator = record["score_denominator"]
    if numerator is not None:
        numerator = _require_integer(numerator, label="score numerator")
    if denominator is not None:
        denominator = _require_integer(denominator, label="score denominator")
    return V2PositionQualitySealState(
        position_id=_require_string(record["position_id"], label="sealed position ID"),
        position_ordinal=_require_integer(
            record["position_ordinal"], label="sealed position ordinal"
        ),
        score_numerator=cast(int | None, numerator),
        score_denominator=cast(int | None, denominator),
        reviewed_subject_count=_require_integer(
            record["reviewed_subject_count"], label="reviewed subject count"
        ),
        baseline_fallback=fallback,
    )


def _adaptation_to_record(item: V2AdaptationSelectionState) -> dict[str, object]:
    return {
        "band": item.band,
        "presentation_id": item.presentation_id,
        "target_id": item.target_id,
    }


def _adaptation_from_record(value: object) -> V2AdaptationSelectionState:
    record = _require_mapping(value, label="adaptation selection")
    _require_exact_keys(
        record,
        expected=frozenset({"band", "presentation_id", "target_id"}),
        label="adaptation selection",
    )
    band = _require_string(record["band"], label="adaptation band")
    if band not in {"corrective", "baseline", "advanced"}:
        raise V2SerializationError(f"unsupported adaptation band: {band!r}")
    return V2AdaptationSelectionState(
        target_id=_require_string(record["target_id"], label="adaptation target ID"),
        presentation_id=_require_string(
            record["presentation_id"], label="adaptation presentation ID"
        ),
        band=cast(Literal["corrective", "baseline", "advanced"], band),
    )


def _stochastic_datum_to_record(item: V2StochasticDatumState) -> dict[str, object]:
    return {
        "key": item.key,
        "uncertainty": item.uncertainty,
        "unit": item.unit,
        "value": item.value,
    }


def _stochastic_datum_from_record(value: object) -> V2StochasticDatumState:
    record = _require_mapping(value, label="stochastic datum")
    _require_exact_keys(
        record,
        expected=frozenset({"key", "uncertainty", "unit", "value"}),
        label="stochastic datum",
    )
    raw = record["value"]
    if not isinstance(raw, (str, int, float, bool)) or raw is None:
        raise V2SerializationError("stochastic datum value must be scalar")
    return V2StochasticDatumState(
        key=_require_string(record["key"], label="stochastic datum key"),
        value=raw,
        unit=_require_optional_string(record["unit"], label="stochastic datum unit"),
        uncertainty=_require_optional_string(
            record["uncertainty"], label="stochastic datum uncertainty"
        ),
    )


def _stochastic_draw_to_record(item: V2StochasticDrawState) -> dict[str, object]:
    return {
        "purpose": item.purpose,
        "raw_value": item.raw_value,
        "selected_index": item.selected_index,
        "selected_weight": item.selected_weight,
        "upper_bound": item.upper_bound,
    }


def _stochastic_draw_from_record(value: object) -> V2StochasticDrawState:
    record = _require_mapping(value, label="stochastic draw")
    _require_exact_keys(
        record,
        expected=frozenset(
            {"purpose", "raw_value", "selected_index", "selected_weight", "upper_bound"}
        ),
        label="stochastic draw",
    )
    return V2StochasticDrawState(
        purpose=_require_string(record["purpose"], label="stochastic draw purpose"),
        upper_bound=_require_integer(record["upper_bound"], label="draw upper bound"),
        raw_value=_require_integer(record["raw_value"], label="draw value"),
        selected_index=_require_integer(record["selected_index"], label="draw index"),
        selected_weight=_require_integer(record["selected_weight"], label="draw weight"),
    )


def _model_probability_to_record(item: V2ModelProbabilityState) -> dict[str, object]:
    return {"basis_points": item.basis_points, "model_id": item.model_id}


def _model_probability_from_record(value: object) -> V2ModelProbabilityState:
    record = _require_mapping(value, label="model probability")
    _require_exact_keys(
        record,
        expected=frozenset({"basis_points", "model_id"}),
        label="model probability",
    )
    return V2ModelProbabilityState(
        model_id=_require_string(record["model_id"], label="model ID"),
        basis_points=_require_integer(record["basis_points"], label="model basis points"),
    )


def _stochastic_support_to_record(item: V2StochasticModelSupportState) -> dict[str, object]:
    return {
        "models": [_model_probability_to_record(model) for model in item.models],
        "process_id": item.process_id,
    }


def _stochastic_support_from_record(value: object) -> V2StochasticModelSupportState:
    record = _require_mapping(value, label="stochastic model support")
    _require_exact_keys(
        record,
        expected=frozenset({"models", "process_id"}),
        label="stochastic model support",
    )
    models = record["models"]
    if isinstance(models, (str, bytes, bytearray)) or not isinstance(models, Sequence):
        raise V2SerializationError("stochastic support models must be an array")
    return V2StochasticModelSupportState(
        process_id=_require_string(record["process_id"], label="support process ID"),
        models=tuple(_model_probability_from_record(item) for item in models),
    )


def _stochastic_process_to_record(item: V2StochasticProcessState) -> dict[str, object]:
    return {
        "dwell_count": item.dwell_count,
        "last_sequence": item.last_sequence,
        "observation_count": item.observation_count,
        "process_id": item.process_id,
        "state_id": item.state_id,
    }


def _stochastic_process_from_record(value: object) -> V2StochasticProcessState:
    record = _require_mapping(value, label="stochastic process state")
    _require_exact_keys(
        record,
        expected=frozenset(
            {"dwell_count", "last_sequence", "observation_count", "process_id", "state_id"}
        ),
        label="stochastic process state",
    )
    last_sequence = record["last_sequence"]
    if last_sequence is not None:
        last_sequence = _require_integer(last_sequence, label="process last sequence")
    return V2StochasticProcessState(
        process_id=_require_string(record["process_id"], label="process ID"),
        state_id=_require_string(record["state_id"], label="process state ID"),
        observation_count=_require_integer(
            record["observation_count"], label="process observation count"
        ),
        dwell_count=_require_integer(record["dwell_count"], label="process dwell count"),
        last_sequence=last_sequence,
    )


def _stochastic_observation_to_record(
    item: V2StochasticObservationState,
) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "channel_id": item.channel_id,
        "measurements": [_stochastic_datum_to_record(datum) for datum in item.measurements],
        "observed_state_label": item.observed_state_label,
        "outcome_id": item.outcome_id,
        "process_id": item.process_id,
        "public_summary": item.public_summary,
        "sequence": item.sequence,
    }


def _stochastic_observation_from_record(value: object) -> V2StochasticObservationState:
    record = _require_mapping(value, label="stochastic observation")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "action_id",
                "channel_id",
                "measurements",
                "observed_state_label",
                "outcome_id",
                "process_id",
                "public_summary",
                "sequence",
            }
        ),
        label="stochastic observation",
    )
    measurements = record["measurements"]
    if isinstance(measurements, (str, bytes, bytearray)) or not isinstance(
        measurements, Sequence
    ):
        raise V2SerializationError("stochastic measurements must be an array")
    return V2StochasticObservationState(
        process_id=_require_string(record["process_id"], label="observation process ID"),
        action_id=_require_string(record["action_id"], label="observation action ID"),
        channel_id=_require_string(record["channel_id"], label="observation channel ID"),
        outcome_id=_require_string(record["outcome_id"], label="observation outcome ID"),
        public_summary=_require_string(record["public_summary"], label="observation summary"),
        measurements=tuple(_stochastic_datum_from_record(item) for item in measurements),
        sequence=_require_integer(record["sequence"], label="observation sequence"),
        observed_state_label=_require_optional_string(
            record["observed_state_label"], label="observed state label"
        ),
    )


def _stochastic_resolution_to_record(
    item: V2StochasticResolutionState,
) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "algorithm": item.algorithm,
        "algorithm_version": item.algorithm_version,
        "channel_id": item.channel_id,
        "measurements": [_stochastic_datum_to_record(datum) for datum in item.measurements],
        "model_support_after": _stochastic_support_to_record(item.model_support_after),
        "next_state_id": item.next_state_id,
        "observed_state_label": item.observed_state_label,
        "outcome_draw": _stochastic_draw_to_record(item.outcome_draw),
        "outcome_id": item.outcome_id,
        "previous_state_id": item.previous_state_id,
        "process_id": item.process_id,
        "public_summary": item.public_summary,
        "state_advanced": item.state_advanced,
        "transition_draw": (
            _stochastic_draw_to_record(item.transition_draw)
            if item.transition_draw is not None
            else None
        ),
        "weight_table_hash": item.weight_table_hash,
    }


def _stochastic_resolution_from_record(value: object) -> V2StochasticResolutionState:
    record = _require_mapping(value, label="stochastic resolution")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "action_id",
                "algorithm",
                "algorithm_version",
                "channel_id",
                "measurements",
                "model_support_after",
                "next_state_id",
                "observed_state_label",
                "outcome_draw",
                "outcome_id",
                "previous_state_id",
                "process_id",
                "public_summary",
                "state_advanced",
                "transition_draw",
                "weight_table_hash",
            }
        ),
        label="stochastic resolution",
    )
    algorithm = _require_string(record["algorithm"], label="stochastic algorithm")
    if algorithm not in {"hidden_markov", "semi_markov"}:
        raise V2SerializationError(f"unsupported stochastic algorithm: {algorithm!r}")
    advanced = record["state_advanced"]
    if not isinstance(advanced, bool):
        raise V2SerializationError("state_advanced must be boolean")
    measurements = record["measurements"]
    if isinstance(measurements, (str, bytes, bytearray)) or not isinstance(
        measurements, Sequence
    ):
        raise V2SerializationError("stochastic resolution measurements must be an array")
    transition = record["transition_draw"]
    return V2StochasticResolutionState(
        process_id=_require_string(record["process_id"], label="resolution process ID"),
        action_id=_require_string(record["action_id"], label="resolution action ID"),
        channel_id=_require_string(record["channel_id"], label="resolution channel ID"),
        algorithm=cast(Literal["hidden_markov", "semi_markov"], algorithm),
        algorithm_version=_require_integer(
            record["algorithm_version"], label="stochastic algorithm version"
        ),
        previous_state_id=_require_string(
            record["previous_state_id"], label="previous stochastic state ID"
        ),
        next_state_id=_require_string(
            record["next_state_id"], label="next stochastic state ID"
        ),
        state_advanced=advanced,
        observed_state_label=_require_optional_string(
            record["observed_state_label"], label="observed state label"
        ),
        transition_draw=(
            _stochastic_draw_from_record(transition) if transition is not None else None
        ),
        outcome_draw=_stochastic_draw_from_record(record["outcome_draw"]),
        outcome_id=_require_string(record["outcome_id"], label="stochastic outcome ID"),
        public_summary=_require_string(record["public_summary"], label="stochastic summary"),
        measurements=tuple(_stochastic_datum_from_record(item) for item in measurements),
        model_support_after=_stochastic_support_from_record(record["model_support_after"]),
        weight_table_hash=_require_string(
            record["weight_table_hash"], label="weight-table hash"
        ),
    )



def _strategic_track_to_record(item: V2StrategicTrackState) -> dict[str, object]:
    return {
        "track_id": item.track_id,
        "value": item.value,
        "minimum": item.minimum,
        "maximum": item.maximum,
    }


def _strategic_track_from_record(value: object) -> V2StrategicTrackState:
    record = _require_mapping(value, label="strategic track")
    _require_exact_keys(
        record,
        expected=frozenset({"track_id", "value", "minimum", "maximum"}),
        label="strategic track",
    )
    return V2StrategicTrackState(
        track_id=_require_string(record["track_id"], label="strategic track ID"),
        value=_require_integer(record["value"], label="strategic track value"),
        minimum=_require_integer(record["minimum"], label="strategic track minimum"),
        maximum=_require_integer(record["maximum"], label="strategic track maximum"),
    )


def _strategic_resource_to_record(item: V2StrategicResourceState) -> dict[str, object]:
    return {
        "resource_id": item.resource_id,
        "title": item.title,
        "value": item.value,
        "minimum": item.minimum,
        "maximum": item.maximum,
    }


def _strategic_resource_from_record(value: object) -> V2StrategicResourceState:
    record = _require_mapping(value, label="strategic resource")
    _require_exact_keys(
        record,
        expected=frozenset({"resource_id", "title", "value", "minimum", "maximum"}),
        label="strategic resource",
    )
    return V2StrategicResourceState(
        resource_id=_require_string(record["resource_id"], label="strategic resource ID"),
        title=_require_string(record["title"], label="strategic resource title"),
        value=_require_integer(record["value"], label="strategic resource value"),
        minimum=_require_integer(record["minimum"], label="strategic resource minimum"),
        maximum=_require_integer(record["maximum"], label="strategic resource maximum"),
    )


def _strategic_condition_to_record(item: V2StrategicConditionState) -> dict[str, object]:
    return {
        "condition_id": item.condition_id,
        "duration": item.duration,
        "created_round": item.created_round,
        "expires_after_round": item.expires_after_round,
    }


def _strategic_condition_from_record(value: object) -> V2StrategicConditionState:
    record = _require_mapping(value, label="strategic condition")
    _require_exact_keys(
        record,
        expected=frozenset(
            {"condition_id", "duration", "created_round", "expires_after_round"}
        ),
        label="strategic condition",
    )
    duration = _require_string(record["duration"], label="strategic condition duration")
    if duration not in {"round", "next_round", "position", "campaign"}:
        raise V2SerializationError(f"unsupported strategic condition duration: {duration!r}")
    expires_value = record["expires_after_round"]
    return V2StrategicConditionState(
        condition_id=_require_string(record["condition_id"], label="strategic condition ID"),
        duration=cast(Literal["round", "next_round", "position", "campaign"], duration),
        created_round=_require_integer(record["created_round"], label="condition creation round"),
        expires_after_round=(
            None
            if expires_value is None
            else _require_integer(expires_value, label="condition expiry round")
        ),
    )


def _strategic_player_to_record(item: V2StrategicPlayerRoundState) -> dict[str, object]:
    return {
        "player_id": item.player_id,
        "operation_count": item.operation_count,
        "locked_role_id": item.locked_role_id,
        "supported_proposal_ids": sorted(item.supported_proposal_ids),
    }


def _strategic_player_from_record(value: object) -> V2StrategicPlayerRoundState:
    record = _require_mapping(value, label="strategic player")
    _require_exact_keys(
        record,
        expected=frozenset(
            {"player_id", "operation_count", "locked_role_id", "supported_proposal_ids"}
        ),
        label="strategic player",
    )
    return V2StrategicPlayerRoundState(
        player_id=_require_string(record["player_id"], label="strategic player ID"),
        operation_count=_require_integer(
            record["operation_count"], label="strategic operation count"
        ),
        locked_role_id=_require_optional_string(
            record["locked_role_id"], label="strategic locked role ID"
        ),
        supported_proposal_ids=frozenset(
            _require_string_sequence(
                record["supported_proposal_ids"], label="supported proposal IDs"
            )
        ),
    )


def _strategic_proposal_to_record(item: V2StrategicProposalState) -> dict[str, object]:
    return {
        "proposal_id": item.proposal_id,
        "action_id": item.action_id,
        "proposer_player_id": item.proposer_player_id,
        "round_index": item.round_index,
        "required_supporter_count": item.required_supporter_count,
        "supporter_player_ids": sorted(item.supporter_player_ids),
        "definition_hash": item.definition_hash,
        "status": item.status,
    }


def _strategic_proposal_from_record(value: object) -> V2StrategicProposalState:
    record = _require_mapping(value, label="strategic proposal")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "proposal_id", "action_id", "proposer_player_id", "round_index",
                "required_supporter_count", "supporter_player_ids", "definition_hash", "status",
            }
        ),
        label="strategic proposal",
    )
    status = _require_string(record["status"], label="strategic proposal status")
    if status not in {"active", "stale"}:
        raise V2SerializationError(f"unsupported strategic proposal status: {status!r}")
    return V2StrategicProposalState(
        proposal_id=_require_string(record["proposal_id"], label="strategic proposal ID"),
        action_id=_require_string(record["action_id"], label="strategic proposal action ID"),
        proposer_player_id=_require_string(
            record["proposer_player_id"], label="strategic proposal author"
        ),
        round_index=_require_integer(record["round_index"], label="proposal round"),
        required_supporter_count=_require_integer(
            record["required_supporter_count"], label="required supporter count"
        ),
        supporter_player_ids=frozenset(
            _require_string_sequence(
                record["supporter_player_ids"], label="proposal supporter IDs"
            )
        ),
        definition_hash=_require_string(
            record["definition_hash"], label="proposal definition hash"
        ),
        status=cast(Literal["active", "stale"], status),
    )


def _strategic_board_to_record(item: V2StrategicBoardState) -> dict[str, object]:
    return {
        "position_id": item.position_id,
        "round_index": item.round_index,
        "max_rounds": item.max_rounds,
        "capacity_remaining": item.capacity_remaining,
        "capacity_per_round": item.capacity_per_round,
        "coordination": item.coordination,
        "coordination_maximum": item.coordination_maximum,
        "escalation": item.escalation,
        "escalation_maximum": item.escalation_maximum,
        "local_resource": _strategic_resource_to_record(item.local_resource),
        "conditions": [_strategic_condition_to_record(value) for value in item.conditions],
        "players": [_strategic_player_to_record(value) for value in item.players],
        "proposals": [_strategic_proposal_to_record(value) for value in item.proposals],
        "forced_review": item.forced_review,
    }


def _strategic_board_from_record(value: object) -> V2StrategicBoardState:
    record = _require_mapping(value, label="strategic board")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "position_id", "round_index", "max_rounds", "capacity_remaining",
                "capacity_per_round", "coordination", "coordination_maximum", "escalation",
                "escalation_maximum", "local_resource", "conditions", "players", "proposals",
                "forced_review",
            }
        ),
        label="strategic board",
    )
    collections: dict[str, Sequence[object]] = {}
    for key in ("conditions", "players", "proposals"):
        raw = record[key]
        if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
            raise V2SerializationError(f"strategic board {key} must be an array")
        collections[key] = raw
    return V2StrategicBoardState(
        position_id=_require_string(record["position_id"], label="strategic board position"),
        round_index=_require_integer(record["round_index"], label="strategic round"),
        max_rounds=_require_integer(record["max_rounds"], label="strategic max rounds"),
        capacity_remaining=_require_integer(
            record["capacity_remaining"], label="remaining capacity"
        ),
        capacity_per_round=_require_integer(
            record["capacity_per_round"], label="round capacity"
        ),
        coordination=_require_integer(record["coordination"], label="coordination"),
        coordination_maximum=_require_integer(
            record["coordination_maximum"], label="coordination maximum"
        ),
        escalation=_require_integer(record["escalation"], label="escalation"),
        escalation_maximum=_require_integer(
            record["escalation_maximum"], label="escalation maximum"
        ),
        local_resource=_strategic_resource_from_record(record["local_resource"]),
        conditions=tuple(
            _strategic_condition_from_record(item) for item in collections["conditions"]
        ),
        players=tuple(
            _strategic_player_from_record(item) for item in collections["players"]
        ),
        proposals=tuple(
            _strategic_proposal_from_record(item) for item in collections["proposals"]
        ),
        forced_review=_require_boolean(record["forced_review"], label="forced review"),
    )


def _strategic_drift_to_record(item: V2StrategicDriftResolutionState) -> dict[str, object]:
    return {
        "process_id": item.process_id,
        "previous_state_id": item.previous_state_id,
        "next_state_id": item.next_state_id,
        "transition_draw": _stochastic_draw_to_record(item.transition_draw),
        "weight_table_hash": item.weight_table_hash,
    }


def _strategic_drift_from_record(value: object) -> V2StrategicDriftResolutionState:
    record = _require_mapping(value, label="strategic natural drift")
    _require_exact_keys(
        record,
        expected=frozenset(
            {"process_id", "previous_state_id", "next_state_id", "transition_draw", "weight_table_hash"}
        ),
        label="strategic natural drift",
    )
    return V2StrategicDriftResolutionState(
        process_id=_require_string(record["process_id"], label="drift process ID"),
        previous_state_id=_require_string(
            record["previous_state_id"], label="drift previous state ID"
        ),
        next_state_id=_require_string(record["next_state_id"], label="drift next state ID"),
        transition_draw=_stochastic_draw_from_record(record["transition_draw"]),
        weight_table_hash=_require_string(
            record["weight_table_hash"], label="drift weight-table hash"
        ),
    )


def _strategic_outcome_to_record(item: V2StrategicPositionOutcomeState) -> dict[str, object]:
    return {
        "position_id": item.position_id,
        "grade": item.grade,
        "round_index": item.round_index,
        "case_integrity": item.case_integrity,
        "institutional_trust": item.institutional_trust,
        "escalation": item.escalation,
        "asset_ids": list(item.asset_ids),
        "liability_ids": list(item.liability_ids),
    }


def _strategic_outcome_from_record(value: object) -> V2StrategicPositionOutcomeState:
    record = _require_mapping(value, label="strategic position outcome")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "position_id", "grade", "round_index", "case_integrity",
                "institutional_trust", "escalation", "asset_ids", "liability_ids",
            }
        ),
        label="strategic position outcome",
    )
    grade = _require_string(record["grade"], label="strategic outcome grade")
    if grade not in {"controlled", "compromised", "incomplete", "critical"}:
        raise V2SerializationError(f"unsupported strategic outcome grade: {grade!r}")
    return V2StrategicPositionOutcomeState(
        position_id=_require_string(record["position_id"], label="outcome position ID"),
        grade=cast(Literal["controlled", "compromised", "incomplete", "critical"], grade),
        round_index=_require_integer(record["round_index"], label="outcome round"),
        case_integrity=_require_integer(record["case_integrity"], label="outcome integrity"),
        institutional_trust=_require_integer(
            record["institutional_trust"], label="outcome trust"
        ),
        escalation=_require_integer(record["escalation"], label="outcome escalation"),
        asset_ids=_require_string_sequence(record["asset_ids"], label="outcome asset IDs"),
        liability_ids=_require_string_sequence(
            record["liability_ids"], label="outcome liability IDs"
        ),
    )


def _strategic_resolution_to_record(item: V2StrategicResolutionState) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "actor_player_id": item.actor_player_id,
        "capacity_cost": item.capacity_cost,
        "coordination_cost": item.coordination_cost,
        "board_before_hash": item.board_before_hash,
        "board_after": _strategic_board_to_record(item.board_after),
        "campaign_tracks_after": [
            _strategic_track_to_record(value) for value in item.campaign_tracks_after
        ],
        "supporter_player_ids": sorted(item.supporter_player_ids),
        "proposal_id": item.proposal_id,
        "natural_drift": (
            _strategic_drift_to_record(item.natural_drift)
            if item.natural_drift is not None
            else None
        ),
    }


def _strategic_resolution_from_record(value: object) -> V2StrategicResolutionState:
    record = _require_mapping(value, label="strategic resolution")
    _require_exact_keys(
        record,
        expected=frozenset(
            {
                "action_id", "actor_player_id", "capacity_cost", "coordination_cost",
                "board_before_hash", "board_after", "campaign_tracks_after",
                "supporter_player_ids", "proposal_id", "natural_drift",
            }
        ),
        label="strategic resolution",
    )
    tracks = record["campaign_tracks_after"]
    if isinstance(tracks, (str, bytes, bytearray)) or not isinstance(tracks, Sequence):
        raise V2SerializationError("strategic campaign tracks must be an array")
    drift = record["natural_drift"]
    return V2StrategicResolutionState(
        action_id=_require_string(record["action_id"], label="strategic action ID"),
        actor_player_id=_require_string(
            record["actor_player_id"], label="strategic actor player ID"
        ),
        capacity_cost=_require_integer(record["capacity_cost"], label="capacity cost"),
        coordination_cost=_require_integer(
            record["coordination_cost"], label="coordination cost"
        ),
        board_before_hash=_require_string(
            record["board_before_hash"], label="strategic board-before hash"
        ),
        board_after=_strategic_board_from_record(record["board_after"]),
        campaign_tracks_after=tuple(
            _strategic_track_from_record(item) for item in tracks
        ),
        supporter_player_ids=frozenset(
            _require_string_sequence(
                record["supporter_player_ids"], label="strategic supporter IDs"
            )
        ),
        proposal_id=_require_optional_string(
            record["proposal_id"], label="strategic proposal ID"
        ),
        natural_drift=(
            _strategic_drift_from_record(drift) if drift is not None else None
        ),
    )


def state_to_record(state: V2InvestigationState) -> dict[str, object]:
    record: dict[str, object] = {
        "assessments": [assessment_to_record(item) for item in state.assessments],
        "available_evidence_ids": sorted(state.available_evidence_ids),
        "available_location_ids": sorted(state.available_location_ids),
        "completed_action_ids": sorted(state.completed_action_ids),
        "completed_position_ids": sorted(state.completed_position_ids),
        "current_position_id": state.current_position_id,
        "documented_information_gap_ids": sorted(state.documented_information_gap_ids),
        "examined_evidence_ids": sorted(state.examined_evidence_ids),
        "hypotheses": [_hypothesis_to_record(item) for item in state.hypotheses],
        "pack_id": state.pack_id,
        "players": [_player_to_record(item) for item in state.players],
        "preserved_contradiction_ids": sorted(state.preserved_contradiction_ids),
        "revision": state.revision,
        "tested_ordinary_explanation_ids": sorted(state.tested_ordinary_explanation_ids),
    }
    if state.serialization_schema >= 2:
        record.update(
            {
                "adaptation_selections": [
                    _adaptation_to_record(item) for item in state.adaptation_selections
                ],
                "position_quality_seals": [
                    _quality_seal_to_record(item) for item in state.position_quality_seals
                ],
                "promoted_findings": [
                    _promoted_finding_to_record(item) for item in state.promoted_findings
                ],
                "quality_reviews": [
                    _quality_review_to_record(item) for item in state.quality_reviews
                ],
            }
        )
    if state.serialization_schema >= 3:
        record.update(
            {
                "stochastic_model_support": [
                    _stochastic_support_to_record(item)
                    for item in state.stochastic_model_support
                ],
                "stochastic_observations": [
                    _stochastic_observation_to_record(item)
                    for item in state.stochastic_observations
                ],
                "stochastic_processes": [
                    _stochastic_process_to_record(item)
                    for item in state.stochastic_processes
                ],
            }
        )
    if state.serialization_schema >= 4:
        record.update(
            {
                "campaign_tracks": [
                    _strategic_track_to_record(item) for item in state.campaign_tracks
                ],
                "strategic_board": (
                    _strategic_board_to_record(state.strategic_board)
                    if state.strategic_board is not None
                    else None
                ),
                "strategic_position_outcomes": [
                    _strategic_outcome_to_record(item)
                    for item in state.strategic_position_outcomes
                ],
                "campaign_modifier_ids": sorted(state.campaign_modifier_ids),
            }
        )
    return record


def state_from_record(value: object) -> V2InvestigationState:
    record = _require_mapping(value, label="investigation state")
    old_keys = frozenset(
        {
            "assessments",
            "available_evidence_ids",
            "available_location_ids",
            "completed_action_ids",
            "completed_position_ids",
            "current_position_id",
            "documented_information_gap_ids",
            "examined_evidence_ids",
            "hypotheses",
            "pack_id",
            "players",
            "preserved_contradiction_ids",
            "revision",
            "tested_ordinary_explanation_ids",
        }
    )
    new_keys = frozenset(
        {
            "adaptation_selections",
            "position_quality_seals",
            "promoted_findings",
            "quality_reviews",
        }
    )
    stochastic_keys = frozenset(
        {"stochastic_model_support", "stochastic_observations", "stochastic_processes"}
    )
    strategic_keys = frozenset(
        {"campaign_tracks", "strategic_board", "strategic_position_outcomes", "campaign_modifier_ids"}
    )
    schema = (
        4
        if strategic_keys.issubset(record)
        else 3
        if stochastic_keys.issubset(record)
        else 2
        if new_keys.issubset(record)
        else 1
    )
    expected_keys = old_keys
    if schema >= 2:
        expected_keys |= new_keys
    if schema >= 3:
        expected_keys |= stochastic_keys
    if schema >= 4:
        expected_keys |= strategic_keys
    _require_exact_keys(
        record,
        expected=expected_keys,
        label="investigation state",
    )

    players_value = record["players"]
    hypotheses_value = record["hypotheses"]
    assessments_value = record["assessments"]
    promoted_findings_value = record.get("promoted_findings", ())
    quality_reviews_value = record.get("quality_reviews", ())
    quality_seals_value = record.get("position_quality_seals", ())
    adaptations_value = record.get("adaptation_selections", ())
    stochastic_processes_value = record.get("stochastic_processes", ())
    stochastic_observations_value = record.get("stochastic_observations", ())
    stochastic_support_value = record.get("stochastic_model_support", ())
    campaign_tracks_value = record.get("campaign_tracks", ())
    strategic_outcomes_value = record.get("strategic_position_outcomes", ())

    for value_to_check, label in (
        (players_value, "players"),
        (hypotheses_value, "hypotheses"),
        (assessments_value, "assessments"),
        (promoted_findings_value, "promoted findings"),
        (quality_reviews_value, "quality reviews"),
        (quality_seals_value, "position quality seals"),
        (adaptations_value, "adaptation selections"),
        (stochastic_processes_value, "stochastic processes"),
        (stochastic_observations_value, "stochastic observations"),
        (stochastic_support_value, "stochastic model support"),
        (campaign_tracks_value, "strategic campaign tracks"),
        (strategic_outcomes_value, "strategic position outcomes"),
    ):
        if isinstance(value_to_check, (str, bytes, bytearray)) or not isinstance(
            value_to_check, Sequence
        ):
            raise V2SerializationError(f"{label} must be a JSON array")

    return V2InvestigationState(
        pack_id=_require_string(record["pack_id"], label="pack ID"),
        current_position_id=_require_string(
            record["current_position_id"],
            label="current position ID",
        ),
        available_location_ids=frozenset(
            _require_string_sequence(
                record["available_location_ids"],
                label="available location IDs",
            )
        ),
        players=tuple(_player_from_record(item) for item in players_value),
        available_evidence_ids=frozenset(
            _require_string_sequence(
                record["available_evidence_ids"],
                label="available evidence IDs",
            )
        ),
        examined_evidence_ids=frozenset(
            _require_string_sequence(
                record["examined_evidence_ids"],
                label="examined evidence IDs",
            )
        ),
        hypotheses=tuple(_hypothesis_from_record(item) for item in hypotheses_value),
        assessments=tuple(assessment_from_record(item) for item in assessments_value),
        completed_action_ids=frozenset(
            _require_string_sequence(
                record["completed_action_ids"],
                label="completed action IDs",
            )
        ),
        tested_ordinary_explanation_ids=frozenset(
            _require_string_sequence(
                record["tested_ordinary_explanation_ids"],
                label="tested ordinary explanation IDs",
            )
        ),
        preserved_contradiction_ids=frozenset(
            _require_string_sequence(
                record["preserved_contradiction_ids"],
                label="preserved contradiction IDs",
            )
        ),
        documented_information_gap_ids=frozenset(
            _require_string_sequence(
                record["documented_information_gap_ids"],
                label="documented information gap IDs",
            )
        ),
        completed_position_ids=frozenset(
            _require_string_sequence(
                record["completed_position_ids"],
                label="completed position IDs",
            )
        ),
        promoted_findings=tuple(
            _promoted_finding_from_record(item) for item in promoted_findings_value
        ),
        quality_reviews=tuple(_quality_review_from_record(item) for item in quality_reviews_value),
        position_quality_seals=tuple(
            _quality_seal_from_record(item) for item in quality_seals_value
        ),
        adaptation_selections=tuple(_adaptation_from_record(item) for item in adaptations_value),
        stochastic_processes=tuple(
            _stochastic_process_from_record(item) for item in stochastic_processes_value
        ),
        stochastic_observations=tuple(
            _stochastic_observation_from_record(item) for item in stochastic_observations_value
        ),
        stochastic_model_support=tuple(
            _stochastic_support_from_record(item) for item in stochastic_support_value
        ),
        campaign_tracks=tuple(
            _strategic_track_from_record(item) for item in campaign_tracks_value
        ),
        strategic_board=(
            _strategic_board_from_record(record["strategic_board"])
            if schema >= 4 and record["strategic_board"] is not None
            else None
        ),
        strategic_position_outcomes=tuple(
            _strategic_outcome_from_record(item) for item in strategic_outcomes_value
        ),
        campaign_modifier_ids=(
            frozenset(
                _require_string_sequence(
                    record["campaign_modifier_ids"], label="campaign modifier IDs"
                )
            )
            if schema >= 4
            else frozenset()
        ),
        revision=_require_integer(record["revision"], label="state revision"),
        serialization_schema=cast(Literal[1, 2, 3, 4], schema),
    )


def _event_payload(event: V2InvestigationEvent) -> dict[str, object]:
    if isinstance(event, V2InvestigationInitializedEvent):
        return {"initial_state": state_to_record(event.initial_state)}

    if isinstance(event, V2PlayerJoinedEvent):
        return {"player": _player_to_record(event.player)}

    if isinstance(event, V2RoleAssignedEvent):
        payload: dict[str, object] = {
            "player_id": event.player_id,
            "role_id": event.role_id,
        }
        if event.display_name is not None or event.description is not None:
            payload["display_name"] = event.display_name
            payload["description"] = event.description
        return payload

    if isinstance(event, V2RoleReleasedEvent):
        return {"player_id": event.player_id, "role_id": event.role_id}

    if isinstance(event, V2PlayerMovedEvent):
        return {
            "from_location_id": event.from_location_id,
            "player_id": event.player_id,
            "to_location_id": event.to_location_id,
        }

    if isinstance(event, V2EvidenceExaminedEvent):
        return {"evidence_id": event.evidence_id, "player_id": event.player_id}

    if isinstance(event, V2ActionPerformedEvent):
        payload: dict[str, object] = {
            "action_id": event.action_id,
            "documented_information_gap_ids": sorted(event.documented_information_gap_ids),
            "player_id": event.player_id,
            "preserved_contradiction_ids": sorted(event.preserved_contradiction_ids),
            "tested_ordinary_explanation_ids": sorted(event.tested_ordinary_explanation_ids),
            "unlocked_evidence_ids": sorted(event.unlocked_evidence_ids),
        }
        if event.stochastic_resolution is not None:
            payload["stochastic_resolution"] = _stochastic_resolution_to_record(
                event.stochastic_resolution
            )
        if event.strategic_resolution is not None:
            payload["strategic_resolution"] = _strategic_resolution_to_record(
                event.strategic_resolution
            )
        return payload

    if isinstance(event, V2ActionProposedEvent):
        return {
            "player_id": event.player_id,
            "proposal": _strategic_proposal_to_record(event.proposal),
            "board_after": _strategic_board_to_record(event.board_after),
            "campaign_tracks_after": [
                _strategic_track_to_record(item) for item in event.campaign_tracks_after
            ],
        }

    if isinstance(event, V2ProposalSupportedEvent):
        return {
            "player_id": event.player_id,
            "proposal": _strategic_proposal_to_record(event.proposal),
            "board_after": _strategic_board_to_record(event.board_after),
            "campaign_tracks_after": [
                _strategic_track_to_record(item) for item in event.campaign_tracks_after
            ],
        }

    if isinstance(event, V2CapacityPassedEvent):
        return {
            "player_id": event.player_id,
            "strategic_resolution": _strategic_resolution_to_record(
                event.strategic_resolution
            ),
        }

    if isinstance(event, V2AssessmentDraftedEvent):
        return {"assessment": assessment_to_record(event.assessment)}

    if isinstance(event, V2AssessmentConfirmedEvent):
        return {
            "assessment_id": event.assessment_id,
            "player_id": event.player_id,
        }

    if isinstance(event, V2PromotedFindingRegisteredEvent):
        return {"finding": _promoted_finding_to_record(event.finding)}

    if isinstance(event, V2QualityReviewSubmittedEvent):
        return {"review": _quality_review_to_record(event.review)}

    if isinstance(event, V2PositionCompletedEvent):
        payload: dict[str, object] = {
            "assessment_id": event.assessment_id,
            "next_position_id": event.next_position_id,
            "player_id": event.player_id,
            "position_id": event.position_id,
            "released_roles": [
                {"player_id": item.player_id, "role_id": item.role_id}
                for item in event.released_roles
            ],
            "unlocked_evidence_ids": sorted(event.unlocked_evidence_ids),
            "unlocked_location_ids": sorted(event.unlocked_location_ids),
        }
        if event.quality_seal is not None or event.adaptation_selection is not None:
            payload["quality_seal"] = (
                _quality_seal_to_record(event.quality_seal)
                if event.quality_seal is not None
                else None
            )
            payload["adaptation_selection"] = (
                _adaptation_to_record(event.adaptation_selection)
                if event.adaptation_selection is not None
                else None
            )
        if event.strategic_outcome is not None:
            payload["strategic_outcome"] = _strategic_outcome_to_record(
                event.strategic_outcome
            )
            payload["campaign_tracks_after"] = [
                _strategic_track_to_record(item) for item in event.campaign_tracks_after
            ]
            payload["campaign_modifier_ids_after"] = sorted(
                event.campaign_modifier_ids_after
            )
        return payload

    raise TypeError(f"unsupported v2 investigation event: {type(event)!r}")


def event_to_record(event: V2InvestigationEvent) -> dict[str, object]:
    schema_version = 2
    if isinstance(event, V2PlayerJoinedEvent):
        schema_version = event.record_schema_version
    elif isinstance(event, V2RoleAssignedEvent) and (
        event.display_name is not None or event.description is not None
    ):
        schema_version = 3
    elif isinstance(event, V2ActionPerformedEvent) and event.strategic_resolution is not None:
        schema_version = 4
    elif isinstance(event, (V2ActionProposedEvent, V2ProposalSupportedEvent, V2CapacityPassedEvent)):
        schema_version = 4
    elif isinstance(event, V2PositionCompletedEvent) and event.strategic_outcome is not None:
        schema_version = 4
    elif isinstance(event, V2ActionPerformedEvent) and event.stochastic_resolution is not None:
        schema_version = 3
    return {
        "event_type": event.event_type,
        "payload": _event_payload(event),
        "schema_version": schema_version,
        "sequence": event.sequence,
        "stream_id": event.stream_id,
    }


def _event_header(
    record: Mapping[str, object],
) -> tuple[int, str, int, str, Mapping[str, object]]:
    _require_exact_keys(
        record,
        expected=frozenset({"event_type", "payload", "schema_version", "sequence", "stream_id"}),
        label="event record",
    )
    schema_version = _require_integer(
        record["schema_version"],
        label="event schema version",
    )

    if schema_version not in {2, 3, 4}:
        raise V2SerializationError(f"unsupported event schema version: {schema_version}")

    return (
        schema_version,
        _require_string(record["event_type"], label="event type"),
        _require_integer(record["sequence"], label="event sequence"),
        _require_string(record["stream_id"], label="stream ID"),
        _require_mapping(record["payload"], label="event payload"),
    )


def event_from_record(value: object) -> V2InvestigationEvent:
    record = _require_mapping(value, label="event record")
    schema_version, event_type, sequence, stream_id, payload = _event_header(record)
    common: dict[str, Any] = {"stream_id": stream_id, "sequence": sequence}

    if event_type == "investigation_initialized":
        _require_exact_keys(
            payload,
            expected=frozenset({"initial_state"}),
            label="investigation-initialized payload",
        )
        return V2InvestigationInitializedEvent(
            **common,
            initial_state=state_from_record(payload["initial_state"]),
        )

    if event_type == "player_joined":
        _require_exact_keys(
            payload,
            expected=frozenset({"player"}),
            label="player-joined payload",
        )
        if schema_version not in (2, 3):
            raise V2SerializationError(
                f"unsupported player-joined event schema version: {schema_version}"
            )
        return V2PlayerJoinedEvent(
            **common,
            player=_player_from_record(payload["player"]),
            record_schema_version=cast(Literal[2, 3], schema_version),
        )

    if event_type in {"role_assigned", "role_released"}:
        base_role_keys = frozenset({"player_id", "role_id"})
        custom_role = event_type == "role_assigned" and "display_name" in payload
        _require_exact_keys(
            payload,
            expected=base_role_keys | (
                frozenset({"display_name", "description"}) if custom_role else frozenset()
            ),
            label=f"{event_type} payload",
        )
        if event_type == "role_assigned":
            return V2RoleAssignedEvent(
                **common,
                player_id=_require_string(payload["player_id"], label="player ID"),
                role_id=_require_string(payload["role_id"], label="role ID"),
                display_name=(
                    _require_optional_string(payload["display_name"], label="role display name")
                    if custom_role
                    else None
                ),
                description=(
                    _require_optional_string(payload["description"], label="role description")
                    if custom_role
                    else None
                ),
            )
        return V2RoleReleasedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            role_id=_require_string(payload["role_id"], label="role ID"),
        )

    if event_type == "player_moved":
        _require_exact_keys(
            payload,
            expected=frozenset({"from_location_id", "player_id", "to_location_id"}),
            label="player-moved payload",
        )
        return V2PlayerMovedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            from_location_id=_require_string(
                payload["from_location_id"],
                label="origin location ID",
            ),
            to_location_id=_require_string(
                payload["to_location_id"],
                label="destination location ID",
            ),
        )

    if event_type == "evidence_examined":
        _require_exact_keys(
            payload,
            expected=frozenset({"evidence_id", "player_id"}),
            label="evidence-examined payload",
        )
        return V2EvidenceExaminedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            evidence_id=_require_string(
                payload["evidence_id"],
                label="evidence ID",
            ),
        )

    if event_type == "action_performed":
        base_action_keys = frozenset(
            {
                "action_id",
                "documented_information_gap_ids",
                "player_id",
                "preserved_contradiction_ids",
                "tested_ordinary_explanation_ids",
                "unlocked_evidence_ids",
            }
        )
        stochastic_action = "stochastic_resolution" in payload
        strategic_action = "strategic_resolution" in payload
        if stochastic_action and schema_version < 3:
            raise V2SerializationError(
                "schema-2 action events cannot contain stochastic resolution data"
            )
        if strategic_action and schema_version < 4:
            raise V2SerializationError(
                "strategic action events require schema version 4"
            )
        optional_action_keys = frozenset(
            key
            for key, present in (
                ("stochastic_resolution", stochastic_action),
                ("strategic_resolution", strategic_action),
            )
            if present
        )
        _require_exact_keys(
            payload,
            expected=base_action_keys | optional_action_keys,
            label="action-performed payload",
        )
        return V2ActionPerformedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            action_id=_require_string(payload["action_id"], label="action ID"),
            unlocked_evidence_ids=frozenset(
                _require_string_sequence(
                    payload["unlocked_evidence_ids"],
                    label="unlocked evidence IDs",
                )
            ),
            tested_ordinary_explanation_ids=frozenset(
                _require_string_sequence(
                    payload["tested_ordinary_explanation_ids"],
                    label="tested ordinary explanation IDs",
                )
            ),
            preserved_contradiction_ids=frozenset(
                _require_string_sequence(
                    payload["preserved_contradiction_ids"],
                    label="preserved contradiction IDs",
                )
            ),
            documented_information_gap_ids=frozenset(
                _require_string_sequence(
                    payload["documented_information_gap_ids"],
                    label="documented information gap IDs",
                )
            ),
            stochastic_resolution=(
                _stochastic_resolution_from_record(payload["stochastic_resolution"])
                if stochastic_action
                else None
            ),
            strategic_resolution=(
                _strategic_resolution_from_record(payload["strategic_resolution"])
                if strategic_action
                else None
            ),
        )

    if event_type in {"action_proposed", "proposal_supported"}:
        if schema_version < 4:
            raise V2SerializationError("strategic proposal events require schema version 4")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {"player_id", "proposal", "board_after", "campaign_tracks_after"}
            ),
            label=f"{event_type} payload",
        )
        tracks = payload["campaign_tracks_after"]
        if isinstance(tracks, (str, bytes, bytearray)) or not isinstance(tracks, Sequence):
            raise V2SerializationError("proposal campaign tracks must be an array")
        common_fields = {
            **common,
            "player_id": _require_string(payload["player_id"], label="player ID"),
            "proposal": _strategic_proposal_from_record(payload["proposal"]),
            "board_after": _strategic_board_from_record(payload["board_after"]),
            "campaign_tracks_after": tuple(
                _strategic_track_from_record(item) for item in tracks
            ),
        }
        if event_type == "action_proposed":
            return V2ActionProposedEvent(**common_fields)
        return V2ProposalSupportedEvent(**common_fields)

    if event_type == "capacity_passed":
        if schema_version < 4:
            raise V2SerializationError("capacity-pass events require schema version 4")
        _require_exact_keys(
            payload,
            expected=frozenset({"player_id", "strategic_resolution"}),
            label="capacity-passed payload",
        )
        return V2CapacityPassedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            strategic_resolution=_strategic_resolution_from_record(
                payload["strategic_resolution"]
            ),
        )

    if event_type == "assessment_drafted":
        _require_exact_keys(
            payload,
            expected=frozenset({"assessment"}),
            label="assessment-drafted payload",
        )
        return V2AssessmentDraftedEvent(
            **common,
            assessment=assessment_from_record(payload["assessment"]),
        )

    if event_type == "assessment_confirmed":
        _require_exact_keys(
            payload,
            expected=frozenset({"assessment_id", "player_id"}),
            label="assessment-confirmed payload",
        )
        return V2AssessmentConfirmedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            assessment_id=_require_string(
                payload["assessment_id"],
                label="assessment ID",
            ),
        )

    if event_type == "promoted_finding_registered":
        _require_exact_keys(
            payload,
            expected=frozenset({"finding"}),
            label="promoted-finding-registered payload",
        )
        return V2PromotedFindingRegisteredEvent(
            **common,
            finding=_promoted_finding_from_record(payload["finding"]),
        )

    if event_type == "quality_review_submitted":
        _require_exact_keys(
            payload,
            expected=frozenset({"review"}),
            label="quality-review-submitted payload",
        )
        return V2QualityReviewSubmittedEvent(
            **common,
            review=_quality_review_from_record(payload["review"]),
        )

    if event_type == "position_completed":
        legacy_keys = frozenset(
            {
                "assessment_id",
                "next_position_id",
                "player_id",
                "position_id",
                "released_roles",
                "unlocked_evidence_ids",
                "unlocked_location_ids",
            }
        )
        adaptive_keys = frozenset({"adaptation_selection", "quality_seal"})
        strategic_position_keys = frozenset(
            {"strategic_outcome", "campaign_tracks_after", "campaign_modifier_ids_after"}
        )
        is_adaptive = adaptive_keys.issubset(payload)
        is_strategic = strategic_position_keys.issubset(payload)
        if is_strategic and schema_version < 4:
            raise V2SerializationError("strategic position completion requires schema version 4")
        _require_exact_keys(
            payload,
            expected=(
                legacy_keys
                | (adaptive_keys if is_adaptive else frozenset())
                | (strategic_position_keys if is_strategic else frozenset())
            ),
            label="position-completed payload",
        )
        released_value = payload["released_roles"]

        if isinstance(released_value, (str, bytes, bytearray)) or not isinstance(
            released_value, Sequence
        ):
            raise V2SerializationError("released roles must be a JSON array")

        released_roles: list[V2ReleasedRole] = []
        for item in released_value:
            released = _require_mapping(item, label="released role")
            _require_exact_keys(
                released,
                expected=frozenset({"player_id", "role_id"}),
                label="released role",
            )
            released_roles.append(
                V2ReleasedRole(
                    player_id=_require_string(
                        released["player_id"],
                        label="released-role player ID",
                    ),
                    role_id=_require_string(
                        released["role_id"],
                        label="released role ID",
                    ),
                )
            )

        return V2PositionCompletedEvent(
            **common,
            player_id=_require_string(payload["player_id"], label="player ID"),
            position_id=_require_string(
                payload["position_id"],
                label="position ID",
            ),
            assessment_id=_require_string(
                payload["assessment_id"],
                label="assessment ID",
            ),
            next_position_id=_require_optional_string(
                payload["next_position_id"],
                label="next position ID",
            ),
            unlocked_location_ids=frozenset(
                _require_string_sequence(
                    payload["unlocked_location_ids"],
                    label="unlocked location IDs",
                )
            ),
            unlocked_evidence_ids=frozenset(
                _require_string_sequence(
                    payload["unlocked_evidence_ids"],
                    label="unlocked evidence IDs",
                )
            ),
            released_roles=tuple(released_roles),
            quality_seal=(
                _quality_seal_from_record(payload["quality_seal"])
                if is_adaptive and payload["quality_seal"] is not None
                else None
            ),
            adaptation_selection=(
                _adaptation_from_record(payload["adaptation_selection"])
                if is_adaptive and payload["adaptation_selection"] is not None
                else None
            ),
            strategic_outcome=(
                _strategic_outcome_from_record(payload["strategic_outcome"])
                if is_strategic
                else None
            ),
            campaign_tracks_after=(
                tuple(
                    _strategic_track_from_record(item)
                    for item in payload["campaign_tracks_after"]
                )
                if is_strategic
                and isinstance(payload["campaign_tracks_after"], Sequence)
                and not isinstance(payload["campaign_tracks_after"], (str, bytes, bytearray))
                else ()
            ),
            campaign_modifier_ids_after=(
                frozenset(
                    _require_string_sequence(
                        payload["campaign_modifier_ids_after"],
                        label="campaign modifier IDs after",
                    )
                )
                if is_strategic
                else frozenset()
            ),
        )

    raise V2SerializationError(f"unsupported event type: {event_type!r}")


def _load_json(data: bytes | bytearray | memoryview | str, *, label: str) -> object:
    try:
        if isinstance(data, str):
            text = data
        else:
            text = bytes(data).decode("utf-8")

        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2SerializationError(f"invalid {label} JSON: {exc}") from exc


def serialize_event(event: V2InvestigationEvent) -> bytes:
    return canonical_json_bytes(event_to_record(event))


def deserialize_event(
    data: bytes | bytearray | memoryview | str,
) -> V2InvestigationEvent:
    return event_from_record(_load_json(data, label="event"))


def serialize_state(state: V2InvestigationState) -> bytes:
    record = {
        "schema_version": V2_STATE_SCHEMA_VERSION,
        "state": state_to_record(state),
    }
    return canonical_json_bytes(record)


def deserialize_state(
    data: bytes | bytearray | memoryview | str,
) -> V2InvestigationState:
    record = _require_mapping(_load_json(data, label="state"), label="state record")
    _require_exact_keys(
        record,
        expected=frozenset({"schema_version", "state"}),
        label="state record",
    )
    schema_version = _require_integer(
        record["schema_version"],
        label="state schema version",
    )

    if schema_version != V2_STATE_SCHEMA_VERSION:
        raise V2SerializationError(f"unsupported state schema version: {schema_version}")

    return state_from_record(record["state"])
