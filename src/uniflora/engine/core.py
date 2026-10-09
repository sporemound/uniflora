from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from uniflora.engine.actions import CandidateAction, UnknownAction
from uniflora.engine.validation import ActionValidator, ValidationContext, ValidationDecision
from uniflora.runtime import SessionMode
from uniflora.storage.repository import GameRepository, MutationPlan, SessionRef


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    accepted: bool
    reason_key: str
    event_id: str | None = None
    event_type: str | None = None
    narration_key: str | None = None
    public_data: dict[str, Any] | None = None
    duplicate: bool = False
    position_completed: bool = False
    state_after: dict[str, Any] | None = None


class DeterministicEngine:
    """Serializes a session locally while the repository locks it across processes."""

    def __init__(self, repository: GameRepository, validator: ActionValidator) -> None:
        self.repository = repository
        self.validator = validator
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def process(
        self,
        ref: SessionRef,
        *,
        participant_id: str,
        action: CandidateAction,
        idempotency_key: str,
    ) -> EngineOutcome:
        if isinstance(action, UnknownAction):
            return EngineOutcome(False, "unknown_action")
        if participant_id.startswith("test:") and ref.environment.value != "test":
            return EngineOutcome(False, "simulated_identity_forbidden")

        decision_holder: dict[str, Any] = {}

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if state["mode"] != SessionMode.RUNNING.value:
                decision_holder["decision"] = ValidationDecision(
                    False, "session_not_running", narration_key="invalid_action"
                )
                return None
            context = ValidationContext(
                environment=ref.environment,
                session_id=ref.session_id,
                participant_id=participant_id,
                action_id=idempotency_key,
                current_position=int(state["current_position"]),
                response_profile=str(state["response_profile"]),
                state=dict(state.get("data", {})),
            )
            decision = self.validator.validate(action, context)
            decision_holder["decision"] = decision
            if not decision.accepted or decision.next_state is None or not decision.event_type:
                return None
            after = dict(state)
            after["data"] = decision.next_state
            if decision.position_completed:
                if decision.next_position is not None:
                    after["current_position"] = decision.next_position
                if decision.next_response_profile is not None:
                    after["response_profile"] = decision.next_response_profile
            completion_key = None
            if decision.position_completed:
                generation = int(context.state.get("session_generation", 0))
                completion_key = (
                    f"generation:{generation}:position:{context.current_position}:completed"
                )
            return MutationPlan(
                event_type=decision.event_type,
                state_after=after,
                payload={"action": action.model_dump(mode="json"), **decision.public_data},
                contribution_function=decision.contribution_function,
                relational_target=decision.relational_target,
                relation_type=decision.relation_type,
                completion_key=completion_key,
                unlocked_observation_key=decision.unlocked_observation_key,
                proposal_projection=decision.proposal_projection,
                confirmation_projection=decision.confirmation_projection,
                proposal_status_update=decision.proposal_status_update,
                proposal_data_update=decision.proposal_data_update,
                summary_projection=decision.summary_projection,
                world_flag_projections=decision.world_flag_projections,
            )

        async with self._locks[ref.session_id]:
            result = await self.repository.mutate(
                ref,
                actor_id=participant_id,
                idempotency_key=idempotency_key,
                planner=planner,
            )
        if result.duplicate:
            return EngineOutcome(
                True,
                "duplicate_event",
                event_id=result.event_id,
                event_type=result.event_type,
                duplicate=True,
                state_after=result.state_after,
            )
        decision = decision_holder.get("decision")
        if not result.accepted or decision is None:
            reason = decision.reason_key if decision is not None else result.reason or "rejected"
            return EngineOutcome(
                False,
                reason,
                narration_key=decision.narration_key if decision is not None else None,
                public_data=decision.public_data if decision is not None else None,
            )
        return EngineOutcome(
            True,
            decision.reason_key,
            event_id=result.event_id,
            event_type=result.event_type,
            narration_key=decision.narration_key,
            public_data=decision.public_data,
            position_completed=decision.position_completed,
            state_after=result.state_after,
        )
