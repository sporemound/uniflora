from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from uniflora.engine.actions import CandidateAction
from uniflora.runtime import Environment


@dataclass(frozen=True, slots=True)
class ValidationContext:
    environment: Environment
    session_id: str
    participant_id: str
    action_id: str
    current_position: int
    response_profile: str
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    accepted: bool
    reason_key: str
    public_data: dict[str, Any] = field(default_factory=dict)
    next_state: dict[str, Any] | None = None
    event_type: str | None = None
    narration_key: str | None = None
    contribution_function: str | None = None
    relational_target: str | None = None
    relation_type: str | None = None
    position_completed: bool = False
    next_position: int | None = None
    next_response_profile: str | None = None
    unlocked_observation_key: str | None = None
    proposal_projection: dict[str, Any] | None = None
    confirmation_projection: dict[str, Any] | None = None
    proposal_status_update: dict[str, str] | None = None
    proposal_data_update: dict[str, Any] | None = None
    summary_projection: dict[str, Any] | None = None
    world_flag_projections: dict[str, Any] = field(default_factory=dict)


class ActionValidator(Protocol):
    def validate(
        self, action: CandidateAction, context: ValidationContext
    ) -> ValidationDecision: ...


class RejectUntilContentLoaded:
    """Safe Phase 2 default: no puzzle action mutates without loaded deterministic rules."""

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        del action, context
        return ValidationDecision(False, "content_not_loaded")
