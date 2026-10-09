from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uniflora.difficulty import (
    DEFAULT_DIFFICULTY,
    DIFFICULTY_POLL_ID,
    MAX_DIFFICULTY_CHANGES_PER_BALLOT,
    DifficultyBallot,
    DifficultyLevel,
    DifficultyPreference,
    DifficultySelectionResult,
    parse_difficulty_level,
)
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode, SessionSnapshot
from uniflora.storage.database import Database
from uniflora.storage.models import (
    ApiUsageRecord,
    BackupRecord,
    Checkpoint,
    Confirmation,
    Contribution,
    DifficultySelectionEvent,
    EventLog,
    GameSession,
    GuildConfiguration,
    NarrationHistory,
    Player,
    PlayerDifficultyPreference,
    RateLimitRecord,
    ReconstructionProposal,
    RelationalContribution,
    RuntimeControl,
    SimulatedIdentity,
    Summary,
    TestIdentitySelection,
    UnlockedObservation,
    WorldFlag,
)
from uniflora.storage.models import DifficultyBallot as DifficultyBallotModel

DEFAULT_TEST_IDENTITIES = (
    "observer",
    "carrier",
    "binder",
    "cultivator",
    "witness",
    "counterweight",
)
DEFAULT_FEATURE_FLAGS = {
    "natural_language": True,
    "gpt_narration": True,
    "tactical_stack": True,
    "triggered_reactions": True,
    "proposal_kickers": True,
    "daily_backup": True,
}
_IDENTITY_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_MAX_DISCORD_ID = 2**63 - 1
_MAX_DIFFICULTY_BALLOTS_PER_SESSION = 32


def _discord_id(value: int, *, label: str) -> int:
    normalized = int(value)
    if normalized <= 0 or normalized > _MAX_DISCORD_ID:
        raise DifficultyBallotError(f"{label} is outside the supported Discord ID range")
    return normalized


def _difficulty_ballot(model: DifficultyBallotModel) -> DifficultyBallot:
    return DifficultyBallot(
        ballot_id=model.id,
        poll_id=model.poll_id,
        environment=model.environment,
        guild_id=model.guild_id,
        channel_id=model.channel_id,
        message_id=model.message_id,
        status=model.status,
        revision=model.revision,
    )


def _difficulty_preference(
    model: PlayerDifficultyPreference | None,
) -> DifficultyPreference:
    if model is None:
        return DifficultyPreference(
            poll_id=DIFFICULTY_POLL_ID,
            level=DEFAULT_DIFFICULTY,
            revision=0,
        )
    return DifficultyPreference(
        poll_id=model.poll_id,
        level=parse_difficulty_level(model.difficulty_level),
        revision=model.revision,
    )


class StorageError(RuntimeError):
    pass


class SessionScopeError(StorageError):
    pass


class ConcurrentMutation(StorageError):
    pass


class UnsafeImport(StorageError):
    pass


class DifficultyBallotError(StorageError):
    pass


class DifficultyBallotConflict(DifficultyBallotError):
    pass


class DifficultyBallotInactive(DifficultyBallotError):
    pass


@dataclass(frozen=True, slots=True)
class SessionRef:
    session_id: str
    environment: Environment


@dataclass(frozen=True, slots=True)
class MutationPlan:
    event_type: str
    state_after: dict[str, Any]
    payload: dict[str, Any]
    contribution_function: str | None = None
    relational_target: str | None = None
    relation_type: str | None = None
    completion_key: str | None = None
    unlocked_observation_key: str | None = None
    proposal_projection: dict[str, Any] | None = None
    confirmation_projection: dict[str, Any] | None = None
    proposal_status_update: dict[str, str] | None = None
    proposal_data_update: dict[str, Any] | None = None
    rebuild_projections: bool = False
    summary_projection: dict[str, Any] | None = None
    world_flag_projections: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MutationResult:
    accepted: bool
    duplicate: bool = False
    event_id: str | None = None
    event_type: str | None = None
    state_after: dict[str, Any] | None = None
    reason: str | None = None


def _session_state(model: GameSession) -> dict[str, Any]:
    return {
        "mode": model.mode,
        "current_position": model.current_position,
        "response_profile": model.response_profile,
        "data": dict(model.state_data),
        "modified_by_force": model.modified_by_force,
        "version": model.version,
    }


def _apply_session_state(model: GameSession, state: dict[str, Any], *, next_version: int) -> None:
    model.mode = str(state["mode"])
    model.current_position = int(state["current_position"])
    model.response_profile = str(state["response_profile"])
    model.state_data = dict(state.get("data", {}))
    model.modified_by_force = bool(state.get("modified_by_force", False))
    model.version = next_version


class GameRepository:
    """All game state access requires an explicit session ID and environment."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def bootstrap(
        self,
        routing: RoutingSnapshot,
    ) -> tuple[RoutingSnapshot, dict[Environment, SessionRef]]:
        async with self.database.sessions.begin() as db:
            guild = await db.scalar(
                select(GuildConfiguration).where(GuildConfiguration.guild_id == routing.guild_id)
            )
            if guild is None:
                guild = GuildConfiguration(
                    guild_id=routing.guild_id,
                    live_channel_id=routing.live_channel_id,
                    test_channel_id=routing.test_channel_id,
                    mycotroph_role_id=routing.mycotroph_role_id,
                    admin_user_ids=sorted(routing.admin_user_ids),
                    diagnostic_channel_id=routing.diagnostic_channel_id,
                )
                db.add(guild)
                await db.flush()
            else:
                # Administrator IDs remain environment-authoritative security configuration.
                guild.admin_user_ids = sorted(routing.admin_user_ids)

            refs: dict[Environment, SessionRef] = {}
            for environment in Environment:
                model = await db.scalar(
                    select(GameSession).where(
                        GameSession.guild_configuration_id == guild.id,
                        GameSession.environment == environment.value,
                    )
                )
                if model is None:
                    model = GameSession(
                        guild_configuration_id=guild.id,
                        environment=environment.value,
                        state_data={"confirmed_facts": []},
                    )
                    db.add(model)
                    await db.flush()
                refs[environment] = SessionRef(model.id, environment)
                control = await db.scalar(
                    select(RuntimeControl).where(RuntimeControl.session_id == model.id)
                )
                if control is None:
                    db.add(
                        RuntimeControl(
                            session_id=model.id,
                            environment=environment.value,
                            feature_flags=dict(DEFAULT_FEATURE_FLAGS),
                        )
                    )

            test_ref = refs[Environment.TEST]
            for slug in DEFAULT_TEST_IDENTITIES:
                await self._ensure_identity(db, test_ref, slug, 0)

            persisted_routing = RoutingSnapshot(
                guild_id=guild.guild_id,
                live_channel_id=guild.live_channel_id,
                test_channel_id=guild.test_channel_id,
                mycotroph_role_id=guild.mycotroph_role_id,
                admin_user_ids=frozenset(guild.admin_user_ids),
                diagnostic_channel_id=guild.diagnostic_channel_id,
            )
            return persisted_routing, refs

    async def session_snapshot(self, ref: SessionRef) -> SessionSnapshot:
        async with self.database.sessions() as db:
            model = await self._require_session(db, ref)
            updated_at = model.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            return SessionSnapshot(
                ref.environment,
                SessionMode(model.mode),
                updated_at.astimezone(UTC).isoformat(),
            )

    async def state(self, ref: SessionRef) -> dict[str, Any]:
        async with self.database.sessions() as db:
            return _session_state(await self._require_session(db, ref))

    async def mutate(
        self,
        ref: SessionRef,
        *,
        actor_id: str,
        idempotency_key: str | None,
        planner: Callable[[dict[str, Any]], MutationPlan | None],
    ) -> MutationResult:
        try:
            async with self.database.sessions.begin() as db:
                if idempotency_key:
                    existing = await db.scalar(
                        select(EventLog).where(
                            EventLog.session_id == ref.session_id,
                            EventLog.environment == ref.environment.value,
                            EventLog.idempotency_key == idempotency_key,
                        )
                    )
                    if existing is not None:
                        return MutationResult(
                            accepted=True,
                            duplicate=True,
                            event_id=existing.id,
                            event_type=existing.event_type,
                            state_after=dict(existing.state_after),
                        )

                model = await self._require_session(db, ref, for_update=True)
                before = _session_state(model)
                plan = planner(dict(before))
                if plan is None:
                    return MutationResult(accepted=False, reason="action rejected by validator")

                sequence = await self._next_sequence(db, ref)
                after = dict(plan.state_after)
                after["version"] = model.version + 1
                event = EventLog(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    sequence=sequence,
                    event_type=plan.event_type,
                    actor_id=actor_id,
                    idempotency_key=idempotency_key,
                    completion_key=plan.completion_key,
                    payload=plan.payload,
                    state_before=before,
                    state_after=after,
                )
                db.add(event)
                _apply_session_state(model, after, next_version=model.version + 1)
                await db.flush()

                if plan.rebuild_projections:
                    await self._rebuild_projections(db, ref, after, event.id, sequence)

                if plan.contribution_function and not plan.rebuild_projections:
                    db.add(
                        Contribution(
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            event_id=event.id,
                            participant_id=actor_id,
                            function=plan.contribution_function,
                            data=plan.payload,
                        )
                    )
                if plan.relation_type and not plan.rebuild_projections:
                    db.add(
                        RelationalContribution(
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            event_id=event.id,
                            source_participant_id=actor_id,
                            target_participant_id=plan.relational_target,
                            relation_type=plan.relation_type,
                            data=plan.payload,
                        )
                    )
                if plan.unlocked_observation_key and not plan.rebuild_projections:
                    db.add(
                        UnlockedObservation(
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            observation_key=plan.unlocked_observation_key,
                            unlocked_by_event_id=event.id,
                        )
                    )
                if plan.proposal_projection and not plan.rebuild_projections:
                    projection = plan.proposal_projection
                    db.add(
                        ReconstructionProposal(
                            id=str(projection["id"]),
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            author_participant_id=str(projection["author_participant_id"]),
                            status=str(projection.get("status", "pending")),
                            proposal_data=dict(projection["proposal_data"]),
                            event_id=event.id,
                        )
                    )
                if plan.confirmation_projection and not plan.rebuild_projections:
                    projection = plan.confirmation_projection
                    db.add(
                        Confirmation(
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            proposal_id=str(projection["proposal_id"]),
                            participant_id=str(projection["participant_id"]),
                            event_id=event.id,
                        )
                    )
                if plan.proposal_status_update and not plan.rebuild_projections:
                    await db.execute(
                        update(ReconstructionProposal)
                        .where(
                            ReconstructionProposal.id == plan.proposal_status_update["proposal_id"],
                            ReconstructionProposal.session_id == ref.session_id,
                            ReconstructionProposal.environment == ref.environment.value,
                        )
                        .values(status=plan.proposal_status_update["status"])
                    )
                if plan.proposal_data_update and not plan.rebuild_projections:
                    await db.execute(
                        update(ReconstructionProposal)
                        .where(
                            ReconstructionProposal.id == plan.proposal_data_update["proposal_id"],
                            ReconstructionProposal.session_id == ref.session_id,
                            ReconstructionProposal.environment == ref.environment.value,
                        )
                        .values(proposal_data=plan.proposal_data_update["proposal_data"])
                    )
                if plan.summary_projection and not plan.rebuild_projections:
                    projection = plan.summary_projection
                    db.add(
                        Summary(
                            session_id=ref.session_id,
                            environment=ref.environment.value,
                            summary_kind=str(projection.get("summary_kind", "player")),
                            public_text=str(projection["public_text"]),
                            through_event_sequence=sequence,
                        )
                    )
                for flag_key, flag_value in (
                    {} if plan.rebuild_projections else (plan.world_flag_projections or {})
                ).items():
                    existing_flag = await db.scalar(
                        select(WorldFlag).where(
                            WorldFlag.session_id == ref.session_id,
                            WorldFlag.environment == ref.environment.value,
                            WorldFlag.flag_key == flag_key,
                        )
                    )
                    value = {"value": flag_value}
                    if existing_flag is None:
                        db.add(
                            WorldFlag(
                                session_id=ref.session_id,
                                environment=ref.environment.value,
                                flag_key=flag_key,
                                value=value,
                                set_by_event_id=event.id,
                            )
                        )
                    else:
                        existing_flag.value = value
                        existing_flag.set_by_event_id = event.id
                await self._ensure_player(db, ref, actor_id)
                return MutationResult(
                    accepted=True,
                    event_id=event.id,
                    event_type=event.event_type,
                    state_after=after,
                )
        except IntegrityError as exc:
            if idempotency_key:
                existing = await self.event_by_idempotency(ref, idempotency_key)
                if existing is not None:
                    return MutationResult(
                        accepted=True,
                        duplicate=True,
                        event_id=existing["id"],
                        event_type=existing["event_type"],
                        state_after=existing["state_after"],
                    )
            raise ConcurrentMutation("state changed concurrently") from exc

    async def transition(
        self,
        ref: SessionRef,
        target: SessionMode,
        allowed_from: set[SessionMode],
        actor_id: str,
        idempotency_key: str | None = None,
    ) -> MutationResult:
        def planner(state: dict[str, Any]) -> MutationPlan | None:
            current = SessionMode(state["mode"])
            if current is target:
                return MutationPlan(
                    event_type="session.transition.noop",
                    state_after=state,
                    payload={"from": current.value, "to": target.value},
                )
            if current not in allowed_from:
                return None
            after = dict(state)
            after["mode"] = target.value
            return MutationPlan(
                event_type="session.transition",
                state_after=after,
                payload={"from": current.value, "to": target.value},
            )

        return await self.mutate(
            ref, actor_id=actor_id, idempotency_key=idempotency_key, planner=planner
        )

    async def create_checkpoint(self, ref: SessionRef, name: str, actor_id: str) -> str:
        async with self.database.sessions.begin() as db:
            model = await self._require_session(db, ref, for_update=True)
            sequence = await self._next_sequence(db, ref)
            existing = await db.scalar(
                select(Checkpoint).where(
                    Checkpoint.session_id == ref.session_id,
                    Checkpoint.environment == ref.environment.value,
                    Checkpoint.name == name,
                )
            )
            if existing is not None:
                raise StorageError(f"checkpoint already exists: {name}")
            checkpoint = Checkpoint(
                session_id=ref.session_id,
                environment=ref.environment.value,
                name=name,
                event_sequence=max(sequence - 1, 0),
                state_snapshot=_session_state(model),
                created_by=actor_id,
            )
            db.add(checkpoint)
            await db.flush()
            event = EventLog(
                session_id=ref.session_id,
                environment=ref.environment.value,
                sequence=sequence,
                event_type="admin.checkpoint.created",
                actor_id=actor_id,
                payload={"checkpoint_id": checkpoint.id, "name": name},
                state_before=_session_state(model),
                state_after=_session_state(model),
            )
            db.add(event)
            await db.flush()
            return checkpoint.id

    async def rollback_to_checkpoint(
        self, ref: SessionRef, checkpoint_id: str, actor_id: str
    ) -> MutationResult:
        async with self.database.sessions() as db:
            checkpoint = await db.scalar(
                select(Checkpoint).where(
                    Checkpoint.id == checkpoint_id,
                    Checkpoint.session_id == ref.session_id,
                    Checkpoint.environment == ref.environment.value,
                )
            )
            if checkpoint is None:
                raise StorageError("checkpoint does not exist in this session")
            target = dict(checkpoint.state_snapshot)

        return await self.mutate(
            ref,
            actor_id=actor_id,
            idempotency_key=f"rollback:checkpoint:{checkpoint_id}",
            planner=lambda state: MutationPlan(
                event_type="admin.rollback",
                state_after={**target, "mode": state["mode"]},
                payload={
                    "checkpoint_id": checkpoint_id,
                    "restored_sequence": checkpoint.event_sequence,
                },
                rebuild_projections=True,
            ),
        )

    async def rollback_to_event(
        self, ref: SessionRef, event_id: str, actor_id: str
    ) -> MutationResult:
        async with self.database.sessions() as db:
            event = await db.scalar(
                select(EventLog).where(
                    EventLog.id == event_id,
                    EventLog.session_id == ref.session_id,
                    EventLog.environment == ref.environment.value,
                )
            )
            if event is None:
                raise StorageError("event does not exist in this session")
            target = dict(event.state_after)
        return await self.mutate(
            ref,
            actor_id=actor_id,
            idempotency_key=f"rollback:event:{event_id}",
            planner=lambda state: MutationPlan(
                event_type="admin.rollback",
                state_after={**target, "mode": state["mode"]},
                payload={"restored_event_id": event_id, "restored_sequence": event.sequence},
                rebuild_projections=True,
            ),
        )

    async def invalidate_event(
        self, ref: SessionRef, event_id: str, actor_id: str
    ) -> MutationResult:
        async with self.database.sessions.begin() as db:
            model = await self._require_session(db, ref, for_update=True)
            if model.mode != SessionMode.PAUSED.value:
                raise StorageError("pause the session before invalidating an event")
            target = await db.scalar(
                select(EventLog)
                .where(
                    EventLog.id == event_id,
                    EventLog.session_id == ref.session_id,
                    EventLog.environment == ref.environment.value,
                )
                .with_for_update()
            )
            if target is None:
                raise StorageError("event does not exist in this session")
            if target.invalidated_by_event_id is not None:
                raise StorageError("event is already invalidated")
            if "action" not in target.payload:
                raise StorageError("only gameplay events with typed actions may be invalidated")
            before = _session_state(model)
            after = copy.deepcopy(target.state_before)
            after["mode"] = SessionMode.PAUSED.value
            after["version"] = model.version + 1
            sequence = await self._next_sequence(db, ref)
            invalidation = EventLog(
                session_id=ref.session_id,
                environment=ref.environment.value,
                sequence=sequence,
                event_type="admin.event.invalidated",
                actor_id=actor_id,
                idempotency_key=f"invalidate:{event_id}",
                payload={
                    "invalidated_event_id": event_id,
                    "discarded_through_sequence": sequence - 1,
                },
                state_before=before,
                state_after=after,
            )
            db.add(invalidation)
            _apply_session_state(model, after, next_version=model.version + 1)
            await db.flush()
            target.invalidated_by_event_id = invalidation.id
            await self._rebuild_projections(db, ref, after, invalidation.id, sequence)
            await db.flush()
            return MutationResult(
                accepted=True,
                event_id=invalidation.id,
                event_type=invalidation.event_type,
                state_after=after,
            )

    async def reset(
        self,
        ref: SessionRef,
        actor_id: str,
        initial_data: dict[str, Any] | None = None,
    ) -> MutationResult:
        async with self.database.sessions.begin() as db:
            model = await self._require_session(db, ref, for_update=True)
            before = _session_state(model)
            reset_data = copy.deepcopy(initial_data or {"confirmed_facts": []})
            prior_generation = int(before.get("data", {}).get("session_generation", 0))
            reset_data["session_generation"] = prior_generation + 1
            initial = {
                "mode": SessionMode.LOCKED.value,
                "current_position": 0,
                "response_profile": "surface_noise",
                "data": reset_data,
                "modified_by_force": False,
                "version": model.version + 1,
            }
            event = EventLog(
                session_id=ref.session_id,
                environment=ref.environment.value,
                sequence=await self._next_sequence(db, ref),
                event_type="admin.session.reset",
                actor_id=actor_id,
                payload={},
                state_before=before,
                state_after=initial,
            )
            db.add(event)
            _apply_session_state(model, initial, next_version=model.version + 1)
            for projection_model in (
                Contribution,
                UnlockedObservation,
                ReconstructionProposal,
                Confirmation,
                RelationalContribution,
                Summary,
                NarrationHistory,
                WorldFlag,
            ):
                await db.execute(
                    delete(projection_model).where(
                        projection_model.session_id == ref.session_id,
                        projection_model.environment == ref.environment.value,
                    )
                )
            await db.flush()
            return MutationResult(
                accepted=True,
                event_id=event.id,
                event_type=event.event_type,
                state_after=initial,
            )

    async def restart_current_position(
        self, ref: SessionRef, *, actor_id: str, reason: str
    ) -> MutationResult:
        """Restore the exact state recorded when the current position was first entered."""
        async with self.database.sessions.begin() as db:
            model = await self._require_session(db, ref, for_update=True)
            before = _session_state(model)
            position = int(before["current_position"])
            events = (
                await db.scalars(
                    select(EventLog)
                    .where(
                        EventLog.session_id == ref.session_id,
                        EventLog.environment == ref.environment.value,
                    )
                    .order_by(EventLog.sequence.asc())
                )
            ).all()
            baseline: dict[str, Any] | None = None
            for logged in events:
                state_after = dict(logged.state_after)
                state_before = dict(logged.state_before)
                if int(state_after.get("current_position", -1)) == position and int(
                    state_before.get("current_position", -1)
                ) != position:
                    baseline = copy.deepcopy(state_after)
                    break
            if baseline is None:
                raise StorageError("the beginning of the current position is not recorded")

            current_data = before.get("data", {})
            reset_data = copy.deepcopy(baseline.get("data", {}))
            reset_data["session_generation"] = int(
                current_data.get("session_generation", 0)
            ) + 1
            reset_data["settlement_event_history"] = copy.deepcopy(
                current_data.get("settlement_event_history", [])
            )
            reset_data["settlement_restart_count"] = int(
                current_data.get("settlement_restart_count", 0)
            ) + 1
            reset_data.update(
                {
                    "settlement_event": None,
                    "settlement_event_actions_since_last": 0,
                    "settlement_event_trigger_after": 0,
                    "settlement_escalation": 0,
                    "settlement_strain": 0,
                    "settlement_burden": 0,
                    "settlement_lost_capacity": 0,
                    "settlement_last_intervener": None,
                    "settlement_restart_pending": False,
                }
            )
            after = copy.deepcopy(baseline)
            after.update(
                {
                    "mode": before["mode"],
                    "current_position": position,
                    "data": reset_data,
                    "modified_by_force": before.get("modified_by_force", False),
                    "version": model.version + 1,
                }
            )
            sequence = await self._next_sequence(db, ref)
            event = EventLog(
                session_id=ref.session_id,
                environment=ref.environment.value,
                sequence=sequence,
                event_type="settlement.position_restarted",
                actor_id=actor_id,
                payload={"position": position, "reason": reason},
                state_before=before,
                state_after=after,
            )
            db.add(event)
            _apply_session_state(model, after, next_version=model.version + 1)
            await db.flush()
            await self._rebuild_projections(db, ref, after, event.id, sequence)
            await db.flush()
            return MutationResult(
                accepted=True,
                event_id=event.id,
                event_type=event.event_type,
                state_after=after,
            )

    async def initialize_content(
        self, ref: SessionRef, initial_data: dict[str, Any], actor_id: str = "system:content"
    ) -> MutationResult:
        current = await self.state(ref)
        if current["data"].get("content_key"):
            return MutationResult(
                accepted=True,
                duplicate=True,
                state_after=current,
                reason="content already initialized",
            )
        content_key = str(initial_data["content_key"])
        content_version = str(initial_data["content_version"])
        return await self.mutate(
            ref,
            actor_id=actor_id,
            idempotency_key=f"content:init:{content_key}:{content_version}",
            planner=lambda state: MutationPlan(
                event_type="content.initialized",
                state_after={**state, "data": copy.deepcopy(initial_data)},
                payload={"content_key": content_key, "content_version": content_version},
            ),
        )

    async def force_unlock_observation(
        self,
        ref: SessionRef,
        *,
        observation_id: str,
        public_text: str,
        fact_key: str,
        actor_id: str,
    ) -> MutationResult:
        if ref.environment is not Environment.TEST:
            raise SessionScopeError("forced observations are confined to the test session")

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            data = copy.deepcopy(state["data"])
            if observation_id in data.get("unlocked_observations", []):
                return None
            data.setdefault("unlocked_observations", []).append(observation_id)
            data.setdefault("confirmed_facts", []).append(
                {
                    "observation_id": observation_id,
                    "fact_key": fact_key,
                    "public_text": public_text,
                }
            )
            after = dict(state)
            after["data"] = data
            after["modified_by_force"] = True
            return MutationPlan(
                event_type="admin.observation.force_unlocked",
                state_after=after,
                payload={"observation_id": observation_id, "forced": True},
                unlocked_observation_key=observation_id,
            )

        return await self.mutate(ref, actor_id=actor_id, idempotency_key=None, planner=planner)

    async def force_test_event(
        self, ref: SessionRef, *, label: str, note: str, actor_id: str
    ) -> MutationResult:
        self._require_test(ref)
        normalized = label.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", normalized):
            raise StorageError("forced event label must be 2-64 lowercase letters or separators")
        if not note.strip() or len(note) > 500:
            raise StorageError("forced event note must be 1-500 characters")

        def planner(state: dict[str, Any]) -> MutationPlan:
            after = copy.deepcopy(state)
            after["modified_by_force"] = True
            return MutationPlan(
                event_type="admin.test_event.forced",
                state_after=after,
                payload={"label": normalized, "note": note.strip(), "forced": True},
            )

        return await self.mutate(ref, actor_id=actor_id, idempotency_key=None, planner=planner)

    async def force_set_position(
        self,
        ref: SessionRef,
        *,
        position: int,
        initial_data: dict[str, Any],
        actor_id: str,
    ) -> MutationResult:
        self._require_test(ref)
        if position < 0 or position > 6:
            raise StorageError("test position must be between 0 and 6")

        def planner(state: dict[str, Any]) -> MutationPlan:
            after = copy.deepcopy(state)
            after["current_position"] = position
            after["data"] = copy.deepcopy(initial_data)
            after["modified_by_force"] = True
            return MutationPlan(
                event_type="admin.test_position.forced",
                state_after=after,
                payload={"position": position, "forced": True},
                rebuild_projections=True,
            )

        return await self.mutate(ref, actor_id=actor_id, idempotency_key=None, planner=planner)

    async def force_set_profile(
        self, ref: SessionRef, *, profile: str, actor_id: str
    ) -> MutationResult:
        self._require_test(ref)

        def planner(state: dict[str, Any]) -> MutationPlan:
            after = copy.deepcopy(state)
            after["response_profile"] = profile
            after["modified_by_force"] = True
            return MutationPlan(
                event_type="admin.test_profile.forced",
                state_after=after,
                payload={"profile": profile, "forced": True},
            )

        return await self.mutate(ref, actor_id=actor_id, idempotency_key=None, planner=planner)

    async def clear_generated_history(self, ref: SessionRef, actor_id: str) -> None:
        self._require_test(ref)
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            deleted: dict[str, int] = {}
            for model, name in (
                (NarrationHistory, "narration"),
            ):
                result = await db.execute(
                    delete(model).where(
                        model.session_id == ref.session_id,
                        model.environment == ref.environment.value,
                    )
                )
                deleted[name] = int(result.rowcount or 0)
            await self._append_admin_event(
                db,
                ref,
                actor_id=actor_id,
                event_type="admin.test_history.cleared",
                payload={"deleted": deleted, "event_history_preserved": True},
            )
            await db.flush()

    async def export_state(self, ref: SessionRef) -> dict[str, Any]:
        async with self.database.sessions() as db:
            session = await self._require_session(db, ref)
            events = list(
                (
                    await db.scalars(
                        select(EventLog)
                        .where(
                            EventLog.session_id == ref.session_id,
                            EventLog.environment == ref.environment.value,
                        )
                        .order_by(EventLog.sequence)
                    )
                ).all()
            )
            return {
                "format": "uniflora-session-export-v1",
                "exported_at": datetime.now(UTC).isoformat(),
                "session_id": ref.session_id,
                "environment": ref.environment.value,
                "state": _session_state(session),
                "events": [self._event_dict(event) for event in events],
            }

    async def export_json(self, ref: SessionRef) -> str:
        return json.dumps(await self.export_state(ref), indent=2, sort_keys=True)

    async def import_state(
        self,
        ref: SessionRef,
        document: dict[str, Any],
        actor_id: str,
        *,
        allow_cross_environment: bool = False,
    ) -> MutationResult:
        if document.get("format") != "uniflora-session-export-v1":
            raise UnsafeImport("unsupported export format")
        source_environment = document.get("environment")
        if source_environment != ref.environment.value and not allow_cross_environment:
            raise UnsafeImport(
                f"refusing {source_environment!r} export for {ref.environment.value!r} session"
            )
        imported = dict(document.get("state", {}))
        required = {"mode", "current_position", "response_profile", "data"}
        if not required.issubset(imported):
            raise UnsafeImport("export state is incomplete")
        try:
            SessionMode(imported["mode"])
            imported["current_position"] = int(imported["current_position"])
            imported["response_profile"] = str(imported["response_profile"])
            imported["data"] = dict(imported["data"])
        except (TypeError, ValueError) as exc:
            raise UnsafeImport("export state contains invalid values") from exc
        if not 0 <= imported["current_position"] <= 6:
            raise UnsafeImport("export position must be between 0 and 6")
        if not 1 <= len(imported["response_profile"]) <= 64:
            raise UnsafeImport("export response profile is invalid")
        imported["modified_by_force"] = True
        return await self.mutate(
            ref,
            actor_id=actor_id,
            idempotency_key=None,
            planner=lambda _state: MutationPlan(
                event_type="admin.session.imported",
                state_after=imported,
                payload={
                    "source_session_id": document.get("session_id"),
                    "source_environment": source_environment,
                    "cross_environment": source_environment != ref.environment.value,
                },
                rebuild_projections=True,
            ),
        )

    async def list_events(self, ref: SessionRef) -> list[dict[str, Any]]:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            events = (
                await db.scalars(
                    select(EventLog)
                    .where(
                        EventLog.session_id == ref.session_id,
                        EventLog.environment == ref.environment.value,
                    )
                    .order_by(EventLog.sequence)
                )
            ).all()
            return [self._event_dict(event) for event in events]

    async def event_by_idempotency(self, ref: SessionRef, key: str) -> dict[str, Any] | None:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            event = await db.scalar(
                select(EventLog).where(
                    EventLog.session_id == ref.session_id,
                    EventLog.environment == ref.environment.value,
                    EventLog.idempotency_key == key,
                )
            )
            return self._event_dict(event) if event else None

    async def create_test_identity(self, ref: SessionRef, slug: str, admin_user_id: int) -> str:
        self._require_test(ref)
        normalized = slug.strip().lower()
        if not _IDENTITY_SLUG.fullmatch(normalized):
            raise StorageError("identity must be 2-32 lowercase letters, digits, or hyphens")
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            identity = await self._ensure_identity(
                db, ref, normalized, admin_user_id, fail_existing=True
            )
            await self._append_admin_event(
                db,
                ref,
                actor_id=f"discord:{admin_user_id}",
                event_type="admin.test_identity.created",
                payload={"participant_id": identity.participant_id, "slug": normalized},
            )
            return identity.participant_id

    async def list_test_identities(self, ref: SessionRef) -> list[dict[str, str]]:
        self._require_test(ref)
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            identities = (
                await db.scalars(
                    select(SimulatedIdentity)
                    .where(
                        SimulatedIdentity.session_id == ref.session_id,
                        SimulatedIdentity.environment == Environment.TEST.value,
                    )
                    .order_by(SimulatedIdentity.slug)
                )
            ).all()
            return [
                {
                    "participant_id": identity.participant_id,
                    "slug": identity.slug,
                    "display_name": identity.display_name,
                }
                for identity in identities
            ]

    async def select_test_identity(self, ref: SessionRef, slug: str, admin_user_id: int) -> str:
        self._require_test(ref)
        normalized = slug.strip().lower()
        participant_id = f"discord:{admin_user_id}"
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            if normalized != "self":
                identity = await db.scalar(
                    select(SimulatedIdentity).where(
                        SimulatedIdentity.session_id == ref.session_id,
                        SimulatedIdentity.environment == Environment.TEST.value,
                        SimulatedIdentity.slug == normalized,
                    )
                )
                if identity is None:
                    raise StorageError(f"unknown test identity: {normalized}")
                participant_id = identity.participant_id
            selection = await db.scalar(
                select(TestIdentitySelection).where(
                    TestIdentitySelection.session_id == ref.session_id,
                    TestIdentitySelection.environment == Environment.TEST.value,
                    TestIdentitySelection.admin_user_id == admin_user_id,
                )
            )
            if selection is None:
                db.add(
                    TestIdentitySelection(
                        session_id=ref.session_id,
                        environment=Environment.TEST.value,
                        admin_user_id=admin_user_id,
                        participant_id=participant_id,
                    )
                )
            else:
                selection.participant_id = participant_id
            await self._append_admin_event(
                db,
                ref,
                actor_id=f"discord:{admin_user_id}",
                event_type="admin.test_identity.selected",
                payload={"participant_id": participant_id},
            )
            return participant_id

    async def difficulty_preference(
        self,
        ref: SessionRef,
        discord_user_id: int,
    ) -> DifficultyPreference:
        user_id = _discord_id(discord_user_id, label="Discord user ID")
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            model = await db.scalar(
                select(PlayerDifficultyPreference).where(
                    PlayerDifficultyPreference.session_id == ref.session_id,
                    PlayerDifficultyPreference.environment == ref.environment.value,
                    PlayerDifficultyPreference.discord_user_id == user_id,
                    PlayerDifficultyPreference.poll_id == DIFFICULTY_POLL_ID,
                )
            )
            return _difficulty_preference(model)

    async def difficulty_preferences(
        self, ref: SessionRef
    ) -> tuple[tuple[int, str, int], ...]:
        """Read saved choices for private Activity synchronization."""
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            rows = await db.scalars(
                select(PlayerDifficultyPreference).where(
                    PlayerDifficultyPreference.session_id == ref.session_id,
                    PlayerDifficultyPreference.environment == ref.environment.value,
                    PlayerDifficultyPreference.poll_id == DIFFICULTY_POLL_ID,
                )
            )
            return tuple(
                (row.discord_user_id, row.difficulty_level, row.revision)
                for row in rows
            )

    async def active_difficulty_ballot(
        self,
        ref: SessionRef,
    ) -> DifficultyBallot | None:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            model = await db.scalar(
                select(DifficultyBallotModel)
                .where(
                    DifficultyBallotModel.session_id == ref.session_id,
                    DifficultyBallotModel.environment == ref.environment.value,
                    DifficultyBallotModel.poll_id == DIFFICULTY_POLL_ID,
                    DifficultyBallotModel.status == "open",
                    DifficultyBallotModel.active_key == "active",
                )
                .order_by(DifficultyBallotModel.created_at.desc())
            )
            return _difficulty_ballot(model) if model is not None else None

    async def open_difficulty_ballot(
        self,
        ref: SessionRef,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> DifficultyBallot:
        normalized_guild_id = _discord_id(guild_id, label="Discord guild ID")
        normalized_channel_id = _discord_id(channel_id, label="Discord channel ID")
        normalized_message_id = _discord_id(message_id, label="Discord message ID")
        try:
            async with self.database.sessions.begin() as db:
                await self._require_session(db, ref, for_update=True)
                active = await db.scalar(
                    select(DifficultyBallotModel)
                    .where(
                        DifficultyBallotModel.session_id == ref.session_id,
                        DifficultyBallotModel.environment == ref.environment.value,
                        DifficultyBallotModel.poll_id == DIFFICULTY_POLL_ID,
                        DifficultyBallotModel.status == "open",
                        DifficultyBallotModel.active_key == "active",
                    )
                    .with_for_update()
                )
                if active is not None:
                    raise DifficultyBallotConflict(
                        "A Hypha difficulty selector is already open on this surface."
                    )
                ballot_count = await db.scalar(
                    select(func.count(DifficultyBallotModel.id)).where(
                        DifficultyBallotModel.session_id == ref.session_id,
                        DifficultyBallotModel.environment == ref.environment.value,
                        DifficultyBallotModel.poll_id == DIFFICULTY_POLL_ID,
                    )
                )
                if int(ballot_count or 0) >= _MAX_DIFFICULTY_BALLOTS_PER_SESSION:
                    raise DifficultyBallotConflict(
                        "The retained difficulty-selector history has reached its safe limit."
                    )
                model = DifficultyBallotModel(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    poll_id=DIFFICULTY_POLL_ID,
                    guild_id=normalized_guild_id,
                    channel_id=normalized_channel_id,
                    message_id=normalized_message_id,
                    status="open",
                    active_key="active",
                    revision=1,
                )
                db.add(model)
                await db.flush()
                return _difficulty_ballot(model)
        except IntegrityError as exc:
            raise DifficultyBallotConflict(
                "The difficulty selector could not be activated without duplicating state."
            ) from exc

    async def close_difficulty_ballot(
        self,
        ref: SessionRef,
    ) -> DifficultyBallot:
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            model = await db.scalar(
                select(DifficultyBallotModel)
                .where(
                    DifficultyBallotModel.session_id == ref.session_id,
                    DifficultyBallotModel.environment == ref.environment.value,
                    DifficultyBallotModel.poll_id == DIFFICULTY_POLL_ID,
                    DifficultyBallotModel.status == "open",
                    DifficultyBallotModel.active_key == "active",
                )
                .with_for_update()
            )
            if model is None:
                raise DifficultyBallotInactive(
                    "There is no open Hypha difficulty selector on this surface."
                )
            model.status = "closed"
            model.active_key = None
            model.closed_at = datetime.now(UTC)
            model.revision += 1
            await db.flush()
            return _difficulty_ballot(model)

    async def difficulty_ballot_response_count(
        self,
        ref: SessionRef,
        ballot_id: str,
    ) -> int:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            ballot = await db.scalar(
                select(DifficultyBallotModel.id).where(
                    DifficultyBallotModel.id == ballot_id,
                    DifficultyBallotModel.session_id == ref.session_id,
                    DifficultyBallotModel.environment == ref.environment.value,
                )
            )
            if ballot is None:
                raise DifficultyBallotInactive(
                    "The requested Hypha difficulty selector is unavailable."
                )
            count = await db.scalar(
                select(func.count(func.distinct(DifficultySelectionEvent.discord_user_id))).where(
                    DifficultySelectionEvent.ballot_id == ballot_id,
                    DifficultySelectionEvent.session_id == ref.session_id,
                    DifficultySelectionEvent.environment == ref.environment.value,
                )
            )
            return int(count or 0)

    async def record_difficulty_selection(
        self,
        ref: SessionRef,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        discord_user_id: int,
        discord_interaction_id: int,
        level: str | DifficultyLevel,
    ) -> DifficultySelectionResult:
        normalized_guild_id = _discord_id(guild_id, label="Discord guild ID")
        normalized_channel_id = _discord_id(channel_id, label="Discord channel ID")
        normalized_message_id = _discord_id(message_id, label="Discord message ID")
        normalized_user_id = _discord_id(discord_user_id, label="Discord user ID")
        normalized_interaction_id = _discord_id(
            discord_interaction_id,
            label="Discord interaction ID",
        )
        normalized_level = parse_difficulty_level(level)

        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            ballot = await db.scalar(
                select(DifficultyBallotModel)
                .where(
                    DifficultyBallotModel.session_id == ref.session_id,
                    DifficultyBallotModel.environment == ref.environment.value,
                    DifficultyBallotModel.poll_id == DIFFICULTY_POLL_ID,
                    DifficultyBallotModel.guild_id == normalized_guild_id,
                    DifficultyBallotModel.channel_id == normalized_channel_id,
                    DifficultyBallotModel.message_id == normalized_message_id,
                    DifficultyBallotModel.status == "open",
                    DifficultyBallotModel.active_key == "active",
                )
                .with_for_update()
            )
            if ballot is None:
                raise DifficultyBallotInactive(
                    "This Hypha difficulty selector is closed, stale, or copied."
                )

            duplicate = await db.scalar(
                select(DifficultySelectionEvent).where(
                    DifficultySelectionEvent.discord_interaction_id
                    == normalized_interaction_id
                )
            )
            if duplicate is not None:
                if (
                    duplicate.ballot_id != ballot.id
                    or duplicate.discord_user_id != normalized_user_id
                    or duplicate.difficulty_level != normalized_level.value
                ):
                    raise DifficultyBallotError(
                        "The Discord interaction ID conflicts with an earlier selection."
                    )
                return DifficultySelectionResult(
                    preference=DifficultyPreference(
                        poll_id=DIFFICULTY_POLL_ID,
                        level=normalized_level,
                        revision=duplicate.preference_revision,
                    ),
                    changed=False,
                    duplicate=True,
                )

            preference = await db.scalar(
                select(PlayerDifficultyPreference)
                .where(
                    PlayerDifficultyPreference.session_id == ref.session_id,
                    PlayerDifficultyPreference.environment == ref.environment.value,
                    PlayerDifficultyPreference.discord_user_id == normalized_user_id,
                    PlayerDifficultyPreference.poll_id == DIFFICULTY_POLL_ID,
                )
                .with_for_update()
            )
            previous_level = preference.difficulty_level if preference is not None else None
            if previous_level == normalized_level.value:
                return DifficultySelectionResult(
                    preference=_difficulty_preference(preference),
                    changed=False,
                    duplicate=False,
                )

            change_count = await db.scalar(
                select(func.count(DifficultySelectionEvent.id)).where(
                    DifficultySelectionEvent.ballot_id == ballot.id,
                    DifficultySelectionEvent.discord_user_id == normalized_user_id,
                )
            )
            if int(change_count or 0) >= MAX_DIFFICULTY_CHANGES_PER_BALLOT:
                raise DifficultyBallotError(
                    "This account has reached the safe preference-change limit for this selector."
                )

            if preference is None:
                preference = PlayerDifficultyPreference(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    discord_user_id=normalized_user_id,
                    poll_id=DIFFICULTY_POLL_ID,
                    difficulty_level=normalized_level.value,
                    revision=1,
                )
                db.add(preference)
            else:
                preference.difficulty_level = normalized_level.value
                preference.revision += 1

            db.add(
                DifficultySelectionEvent(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    ballot_id=ballot.id,
                    discord_user_id=normalized_user_id,
                    discord_interaction_id=normalized_interaction_id,
                    previous_level=previous_level,
                    difficulty_level=normalized_level.value,
                    preference_revision=preference.revision,
                )
            )
            await db.flush()
            return DifficultySelectionResult(
                preference=_difficulty_preference(preference),
                changed=True,
                duplicate=False,
            )

    async def resolve_participant(self, ref: SessionRef, discord_user_id: int) -> str:
        if ref.environment is Environment.LIVE:
            return f"discord:{discord_user_id}"
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            selection = await db.scalar(
                select(TestIdentitySelection).where(
                    TestIdentitySelection.session_id == ref.session_id,
                    TestIdentitySelection.environment == Environment.TEST.value,
                    TestIdentitySelection.admin_user_id == discord_user_id,
                )
            )
            return selection.participant_id if selection else f"discord:{discord_user_id}"

    async def record_narration(
        self,
        ref: SessionRef,
        *,
        event_id: str,
        profile: str,
        public_text: str,
        generated_by: str,
    ) -> None:
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref)
            db.add(
                NarrationHistory(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    event_id=event_id,
                    profile=profile,
                    public_text=public_text,
                    generated_by=generated_by,
                )
            )

    async def recent_narration(self, ref: SessionRef, *, limit: int) -> list[dict[str, str]]:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            records = (
                await db.scalars(
                    select(NarrationHistory)
                    .where(
                        NarrationHistory.session_id == ref.session_id,
                        NarrationHistory.environment == ref.environment.value,
                    )
                    .order_by(NarrationHistory.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "event_id": record.event_id,
                    "profile": record.profile,
                    "public_text": record.public_text,
                    "generated_by": record.generated_by,
                }
                for record in reversed(records)
            ]

    async def record_api_usage(
        self,
        ref: SessionRef,
        *,
        model: str,
        purpose: str,
        participant_id: str | None,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
    ) -> None:
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref)
            db.add(
                ApiUsageRecord(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    model=model,
                    purpose=purpose,
                    participant_id=participant_id,
                    input_tokens=max(0, input_tokens),
                    cached_input_tokens=max(0, cached_input_tokens),
                    output_tokens=max(0, output_tokens),
                    estimated_cost=max(0.0, estimated_cost),
                )
            )

    async def api_usage_totals(
        self, ref: SessionRef, *, now: datetime | None = None
    ) -> dict[str, float]:
        current = now or datetime.now(UTC)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            base = (
                ApiUsageRecord.session_id == ref.session_id,
                ApiUsageRecord.environment == ref.environment.value,
            )
            daily = await db.scalar(
                select(func.coalesce(func.sum(ApiUsageRecord.estimated_cost), 0.0)).where(
                    *base, ApiUsageRecord.created_at >= day_start
                )
            )
            monthly = await db.scalar(
                select(func.coalesce(func.sum(ApiUsageRecord.estimated_cost), 0.0)).where(
                    *base, ApiUsageRecord.created_at >= month_start
                )
            )
            return {"daily_cost": float(daily or 0), "monthly_cost": float(monthly or 0)}

    async def runtime_control(self, ref: SessionRef) -> dict[str, Any]:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            control = await db.scalar(
                select(RuntimeControl).where(
                    RuntimeControl.session_id == ref.session_id,
                    RuntimeControl.environment == ref.environment.value,
                )
            )
            if control is None:
                raise StorageError("runtime control is not initialized")
            return self._runtime_control_dict(control)

    async def update_runtime_control(
        self,
        ref: SessionRef,
        actor_id: str,
        *,
        fallback_mode: bool | None = None,
        interpretation_model: str | None = None,
        narration_model: str | None = None,
        budget_overrides: dict[str, float] | None = None,
        feature_flag: tuple[str, bool] | None = None,
    ) -> dict[str, Any]:
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref, for_update=True)
            control = await db.scalar(
                select(RuntimeControl)
                .where(
                    RuntimeControl.session_id == ref.session_id,
                    RuntimeControl.environment == ref.environment.value,
                )
                .with_for_update()
            )
            if control is None:
                raise StorageError("runtime control is not initialized")
            changed: dict[str, Any] = {}
            if fallback_mode is not None:
                control.fallback_mode = fallback_mode
                if not fallback_mode:
                    control.consecutive_api_failures = 0
                changed["fallback_mode"] = fallback_mode
            if interpretation_model is not None:
                value = interpretation_model.strip()
                if not value or len(value) > 128:
                    raise StorageError("interpretation model must be 1-128 characters")
                control.interpretation_model = value
                changed["interpretation_model"] = value
            if narration_model is not None:
                value = narration_model.strip()
                if not value or len(value) > 128:
                    raise StorageError("narration model must be 1-128 characters")
                control.narration_model = value
                changed["narration_model"] = value
            if budget_overrides is not None:
                allowed = {
                    "soft_daily",
                    "hard_daily",
                    "soft_monthly",
                    "hard_monthly",
                }
                if set(budget_overrides) - allowed or any(
                    not math.isfinite(value) or value < 0 for value in budget_overrides.values()
                ):
                    raise StorageError("budget overrides are invalid")
                merged = {**control.budget_overrides, **budget_overrides}
                if merged.get("soft_daily", 0) > merged.get("hard_daily", float("inf")):
                    raise StorageError("soft daily budget cannot exceed hard daily budget")
                if merged.get("soft_monthly", 0) > merged.get("hard_monthly", float("inf")):
                    raise StorageError("soft monthly budget cannot exceed hard monthly budget")
                control.budget_overrides = merged
                changed["budget_overrides"] = dict(merged)
            if feature_flag is not None:
                name, enabled = feature_flag
                if name not in DEFAULT_FEATURE_FLAGS:
                    raise StorageError("unknown feature flag")
                flags = {**DEFAULT_FEATURE_FLAGS, **control.feature_flags, name: enabled}
                control.feature_flags = flags
                changed["feature_flag"] = {"name": name, "enabled": enabled}
            await self._append_admin_event(
                db,
                ref,
                actor_id=actor_id,
                event_type="admin.runtime_control.updated",
                payload=changed,
            )
            await db.flush()
            return self._runtime_control_dict(control)

    async def record_api_result(
        self, ref: SessionRef, *, success: bool, failure_threshold: int
    ) -> bool:
        async with self.database.sessions.begin() as db:
            await self._require_session(db, ref)
            control = await db.scalar(
                select(RuntimeControl)
                .where(
                    RuntimeControl.session_id == ref.session_id,
                    RuntimeControl.environment == ref.environment.value,
                )
                .with_for_update()
            )
            if control is None:
                raise StorageError("runtime control is not initialized")
            was_fallback = control.fallback_mode
            if success:
                control.consecutive_api_failures = 0
            else:
                control.consecutive_api_failures += 1
                if control.consecutive_api_failures >= failure_threshold:
                    control.fallback_mode = True
            await db.flush()
            return not was_fallback and control.fallback_mode

    async def event(self, ref: SessionRef, event_id: str) -> dict[str, Any] | None:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            event = await db.scalar(
                select(EventLog).where(
                    EventLog.id == event_id,
                    EventLog.session_id == ref.session_id,
                    EventLog.environment == ref.environment.value,
                )
            )
            return self._event_dict(event) if event else None

    async def latest_clean_completion(self, ref: SessionRef) -> dict[str, Any] | None:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            events = (
                await db.scalars(
                    select(EventLog)
                    .where(
                        EventLog.session_id == ref.session_id,
                        EventLog.environment == ref.environment.value,
                        EventLog.event_type == "position.completed",
                    )
                    .order_by(EventLog.sequence.desc())
                )
            ).all()
            clean = next(
                (event for event in events if not event.state_after.get("modified_by_force")),
                None,
            )
            return self._event_dict(clean) if clean else None

    async def record_backup(self, *, status: str, path: str | None, detail: str = "") -> None:
        async with self.database.sessions.begin() as db:
            db.add(BackupRecord(status=status, path=path, detail=detail[:1000]))

    async def latest_backup(self) -> dict[str, str | None] | None:
        async with self.database.sessions() as db:
            record = await db.scalar(
                select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1)
            )
            if record is None:
                return None
            created_at = record.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return {
                "status": record.status,
                "path": record.path,
                "detail": record.detail,
                "created_at": created_at.astimezone(UTC).isoformat(),
            }

    async def acquire_api_cooldowns(
        self,
        ref: SessionRef,
        participant_id: str,
        *,
        purpose: str,
        per_user_seconds: int,
        global_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        scopes: list[tuple[str, int]] = []
        if global_seconds > 0:
            scopes.append((f"{purpose}:global", global_seconds))
        if per_user_seconds > 0:
            scopes.append((f"{purpose}:user:{participant_id}", per_user_seconds))
        if not scopes:
            return True
        try:
            async with self.database.sessions.begin() as db:
                await self._require_session(db, ref, for_update=True)
                records: list[tuple[RateLimitRecord | None, str, int]] = []
                for scope_key, seconds in scopes:
                    window_key = f"{purpose}:cooldown"
                    record = await db.scalar(
                        select(RateLimitRecord).where(
                            RateLimitRecord.session_id == ref.session_id,
                            RateLimitRecord.environment == ref.environment.value,
                            RateLimitRecord.scope_key == scope_key,
                            RateLimitRecord.window_key == window_key,
                        )
                    )
                    if record is not None:
                        updated_at = record.updated_at
                        if updated_at.tzinfo is None:
                            updated_at = updated_at.replace(tzinfo=UTC)
                        if (current - updated_at).total_seconds() < seconds:
                            return False
                    records.append((record, scope_key, seconds))
                for record, scope_key, _seconds in records:
                    if record is None:
                        db.add(
                            RateLimitRecord(
                                session_id=ref.session_id,
                                environment=ref.environment.value,
                                scope_key=scope_key,
                                window_key=f"{purpose}:cooldown",
                                request_count=1,
                                created_at=current,
                                updated_at=current,
                            )
                        )
                    else:
                        record.request_count += 1
                        record.updated_at = current
                await db.flush()
                return True
        except IntegrityError:
            return False

    async def remove_test_identity(self, ref: SessionRef, slug: str, admin_user_id: int) -> None:
        self._require_test(ref)
        async with self.database.sessions.begin() as db:
            identity = await db.scalar(
                select(SimulatedIdentity).where(
                    SimulatedIdentity.session_id == ref.session_id,
                    SimulatedIdentity.environment == Environment.TEST.value,
                    SimulatedIdentity.slug == slug.lower(),
                )
            )
            if identity is None:
                raise StorageError("test identity not found")
            await db.execute(
                update(TestIdentitySelection)
                .where(
                    TestIdentitySelection.session_id == ref.session_id,
                    TestIdentitySelection.participant_id == identity.participant_id,
                )
                .values(participant_id=f"discord:{admin_user_id}")
            )
            await db.delete(identity)
            await self._append_admin_event(
                db,
                ref,
                actor_id=f"discord:{admin_user_id}",
                event_type="admin.test_identity.removed",
                payload={"participant_id": identity.participant_id, "slug": identity.slug},
            )

    async def update_routing(
        self,
        guild_id: int,
        *,
        live_channel_id: int | None = None,
        test_channel_id: int | None = None,
        role_id: int | None = None,
        diagnostic_channel_id: int | None | object = ...,
    ) -> RoutingSnapshot:
        async with self.database.sessions.begin() as db:
            guild = await db.scalar(
                select(GuildConfiguration)
                .where(GuildConfiguration.guild_id == guild_id)
                .with_for_update()
            )
            if guild is None:
                raise StorageError("guild configuration not initialized")
            new_live = live_channel_id or guild.live_channel_id
            new_test = test_channel_id or guild.test_channel_id
            new_diagnostic = (
                guild.diagnostic_channel_id
                if diagnostic_channel_id is ...
                else diagnostic_channel_id
            )
            if new_live == new_test:
                raise StorageError("live and test channels must remain distinct")
            if new_diagnostic in {new_live, new_test}:
                raise StorageError("diagnostic channel must remain distinct")
            guild.live_channel_id = new_live
            guild.test_channel_id = new_test
            guild.mycotroph_role_id = role_id or guild.mycotroph_role_id
            guild.diagnostic_channel_id = new_diagnostic  # type: ignore[assignment]
            return RoutingSnapshot(
                guild.guild_id,
                guild.live_channel_id,
                guild.test_channel_id,
                guild.mycotroph_role_id,
                frozenset(guild.admin_user_ids),
                guild.diagnostic_channel_id,
            )

    async def count_rows(self, ref: SessionRef, model: type[Any]) -> int:
        async with self.database.sessions() as db:
            await self._require_session(db, ref)
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.session_id == ref.session_id,
                        model.environment == ref.environment.value,
                    )
                )
                or 0
            )

    async def _rebuild_projections(
        self,
        db: AsyncSession,
        ref: SessionRef,
        state: dict[str, Any],
        event_id: str,
        sequence: int,
    ) -> None:
        for model in (
            Confirmation,
            Contribution,
            UnlockedObservation,
            RelationalContribution,
            Summary,
            WorldFlag,
            ReconstructionProposal,
        ):
            await db.execute(
                delete(model).where(
                    model.session_id == ref.session_id,
                    model.environment == ref.environment.value,
                )
            )
        data = state.get("data", {})
        for item in data.get("contributions", []):
            db.add(
                Contribution(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    event_id=event_id,
                    participant_id=str(item["participant_id"]),
                    function=str(item["function"]),
                    data={"action": item.get("action", "recovered")},
                )
            )
        for observation_key in data.get("unlocked_observations", []):
            db.add(
                UnlockedObservation(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    observation_key=str(observation_key),
                    unlocked_by_event_id=event_id,
                )
            )
        for connection in data.get("connections", []):
            db.add(
                RelationalContribution(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    source_participant_id=str(connection.get("participant_id", "system:recovery")),
                    target_participant_id=str(connection.get("target", "")) or None,
                    relation_type="pathway_repair",
                    event_id=event_id,
                    data=dict(connection),
                )
            )
        for offer in data.get("offers", []):
            db.add(
                RelationalContribution(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    source_participant_id=str(offer.get("participant_id", "system:recovery")),
                    target_participant_id=str(offer.get("recipient_id", "")) or None,
                    relation_type="resource_offer",
                    event_id=event_id,
                    data=dict(offer),
                )
            )
        for proposal_id, proposal in data.get("proposals", {}).items():
            db.add(
                ReconstructionProposal(
                    id=str(proposal_id),
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    author_participant_id=str(proposal["author_participant_id"]),
                    status=str(proposal.get("status", "pending")),
                    proposal_data=dict(proposal),
                    event_id=event_id,
                )
            )
        await db.flush()
        for confirmation in data.get("confirmations", []):
            db.add(
                Confirmation(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    proposal_id=str(confirmation["proposal_id"]),
                    participant_id=str(confirmation["participant_id"]),
                    event_id=event_id,
                )
            )
        for summary in data.get("summaries", []):
            db.add(
                Summary(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    summary_kind="confirmed_public",
                    public_text=str(summary["public_text"]),
                    through_event_sequence=sequence,
                )
            )
        for flag_key, flag_value in data.get("world_flags", {}).items():
            db.add(
                WorldFlag(
                    session_id=ref.session_id,
                    environment=ref.environment.value,
                    flag_key=str(flag_key),
                    value={"value": flag_value},
                    set_by_event_id=event_id,
                )
            )

    async def _require_session(
        self, db: AsyncSession, ref: SessionRef, *, for_update: bool = False
    ) -> GameSession:
        statement = select(GameSession).where(
            GameSession.id == ref.session_id,
            GameSession.environment == ref.environment.value,
        )
        if for_update:
            statement = statement.with_for_update()
        model = await db.scalar(statement)
        if model is None:
            raise SessionScopeError(
                f"session {ref.session_id!r} is not a {ref.environment.value!r} session"
            )
        return model

    async def _next_sequence(self, db: AsyncSession, ref: SessionRef) -> int:
        current = await db.scalar(
            select(func.max(EventLog.sequence)).where(
                EventLog.session_id == ref.session_id,
                EventLog.environment == ref.environment.value,
            )
        )
        return int(current or 0) + 1

    async def _append_admin_event(
        self,
        db: AsyncSession,
        ref: SessionRef,
        *,
        actor_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> EventLog:
        model = await self._require_session(db, ref, for_update=True)
        before = _session_state(model)
        model.version += 1
        after = _session_state(model)
        event = EventLog(
            session_id=ref.session_id,
            environment=ref.environment.value,
            sequence=await self._next_sequence(db, ref),
            event_type=event_type,
            actor_id=actor_id,
            payload=payload,
            state_before=before,
            state_after=after,
        )
        db.add(event)
        return event

    async def _ensure_identity(
        self,
        db: AsyncSession,
        ref: SessionRef,
        slug: str,
        admin_user_id: int,
        *,
        fail_existing: bool = False,
    ) -> SimulatedIdentity:
        existing = await db.scalar(
            select(SimulatedIdentity).where(
                SimulatedIdentity.session_id == ref.session_id,
                SimulatedIdentity.environment == Environment.TEST.value,
                SimulatedIdentity.slug == slug,
            )
        )
        if existing is not None:
            if fail_existing:
                raise StorageError(f"test identity already exists: {slug}")
            return existing
        identity = SimulatedIdentity(
            session_id=ref.session_id,
            environment=Environment.TEST.value,
            participant_id=f"test:{slug}",
            slug=slug,
            display_name=slug.replace("-", " ").title(),
            created_by_admin_id=admin_user_id,
        )
        db.add(identity)
        await db.flush()
        return identity

    async def _ensure_player(
        self, db: AsyncSession, ref: SessionRef, participant_id: str
    ) -> Player:
        existing = await db.scalar(
            select(Player).where(
                Player.session_id == ref.session_id,
                Player.environment == ref.environment.value,
                Player.participant_id == participant_id,
            )
        )
        if existing is not None:
            return existing
        simulated = participant_id.startswith("test:")
        if simulated and ref.environment is not Environment.TEST:
            raise SessionScopeError("simulated participants are forbidden in live sessions")
        discord_id = None
        if participant_id.startswith("discord:"):
            discord_id = int(participant_id.removeprefix("discord:"))
        player = Player(
            session_id=ref.session_id,
            environment=ref.environment.value,
            participant_id=participant_id,
            discord_user_id=discord_id,
            display_name=participant_id,
            is_simulated=simulated,
        )
        db.add(player)
        return player

    @staticmethod
    def _runtime_control_dict(control: RuntimeControl) -> dict[str, Any]:
        return {
            "fallback_mode": control.fallback_mode,
            "consecutive_api_failures": control.consecutive_api_failures,
            "interpretation_model": control.interpretation_model,
            "narration_model": control.narration_model,
            "budget_overrides": dict(control.budget_overrides),
            "feature_flags": {**DEFAULT_FEATURE_FLAGS, **control.feature_flags},
        }

    @staticmethod
    def _require_test(ref: SessionRef) -> None:
        if ref.environment is not Environment.TEST:
            raise SessionScopeError("simulated identities exist only in test sessions")

    @staticmethod
    def _event_dict(event: EventLog) -> dict[str, Any]:
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        result = {
            "id": event.id,
            "session_id": event.session_id,
            "environment": event.environment,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "idempotency_key": event.idempotency_key,
            "completion_key": event.completion_key,
            "invalidated_by_event_id": event.invalidated_by_event_id,
            "payload": dict(event.payload),
            "state_before": dict(event.state_before),
            "state_after": dict(event.state_after),
            "created_at": created_at.astimezone(UTC).isoformat(),
        }
        return result
