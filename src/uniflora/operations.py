from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from uniflora.config import Settings
from uniflora.content.validation import validate_packaged_content
from uniflora.engine.actions import CandidateAction
from uniflora.game_service import GameService, PublicResult
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, SessionRef, StorageError


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    text: str
    checks: dict[str, bool]


class OperationsService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        repository: GameRepository,
        refs: dict[Environment, SessionRef],
        game: GameService,
        sessions: Any,
        routing: Any,
    ) -> None:
        self.settings = settings
        self.database = database
        self.repository = repository
        self.refs = refs
        self.game = game
        self.sessions = sessions
        self.routing = routing

    async def startup_integrity(self) -> None:
        database_ok, detail = await self.database.integrity_check()
        if not database_ok:
            raise RuntimeError(f"database integrity check failed: {detail}")
        report = await validate_packaged_content()
        if not report.valid:
            raise RuntimeError("packaged content validation failed")
        for ref in self.refs.values():
            state = await self.repository.state(ref)
            if not isinstance(state.get("data"), dict):
                raise RuntimeError(f"{ref.environment.value} state data is invalid")

    async def live_readiness(self) -> ReadinessReport:
        routing: RoutingSnapshot = self.routing.current
        channel_ids = {
            routing.live_channel_id,
            routing.test_channel_id,
            routing.diagnostic_channel_id,
        }
        channels_valid = (
            routing.live_channel_id > 0
            and routing.test_channel_id > 0
            and routing.diagnostic_channel_id is not None
            and routing.diagnostic_channel_id > 0
            and len(channel_ids) == 3
        )
        database_ok, database_detail = await self.database.integrity_check()
        try:
            content = await validate_packaged_content()
            content_ok = content.valid
        except Exception:
            content_ok = False
        test_state = await self.repository.state(self.refs[Environment.TEST])
        live_state = await self.repository.state(self.refs[Environment.LIVE])
        clean_completion = await self.repository.latest_clean_completion(
            self.refs[Environment.TEST]
        )
        test_clean = not bool(test_state["modified_by_force"])
        live_initial = (
            int(live_state["current_position"]) == 0
            and not live_state["data"].get("unlocked_observations", [])
            and live_state["response_profile"] == "surface_noise"
        )
        live_locked = live_state["mode"] == SessionMode.LOCKED.value
        live_control = await self.repository.runtime_control(self.refs[Environment.LIVE])
        budgets = self._effective_budgets(live_control)
        usage = await self.repository.api_usage_totals(self.refs[Environment.LIVE])
        budget_ok = (
            usage["daily_cost"] < budgets["hard_daily"]
            and usage["monthly_cost"] < budgets["hard_monthly"]
        )
        backup = await self.repository.latest_backup()
        backup_ok = False
        backup_text = "none"
        if backup is not None:
            backup_text = f"{backup['status']} at {backup['created_at']}"
            if backup["status"] == "success":
                created_at = datetime.fromisoformat(str(backup["created_at"]))
                backup_ok = datetime.now(UTC) - created_at <= timedelta(
                    hours=self.settings.backup_interval_hours
                )
        if not self.settings.backup_enabled:
            backup_text = "disabled by configuration"
            backup_ok = False
        elif not live_control["feature_flags"].get("daily_backup", True):
            backup_text = "disabled by live feature flag"
            backup_ok = False
        checks = {
            "channels": channels_valid,
            "database": database_ok,
            "content": content_ok,
            "clean_test_completion": clean_completion is not None,
            "test_not_force_modified": test_clean,
            "live_initial": live_initial,
            "api_budget": budget_ok,
            "backup": backup_ok,
            "live_locked": live_locked,
        }
        ready = all(checks.values())
        lines = [
            f"Live readiness: {'READY' if ready else 'NOT READY'}",
            f"* channels configured: {self._mark(channels_valid)}",
            f"* database integrity: {self._mark(database_ok)} ({database_detail})",
            f"* content and Position 0 simulation: {self._mark(content_ok)}",
            "* most recent clean test completion: "
            + (str(clean_completion["created_at"]) if clean_completion else "none"),
            f"* test modified by force: {'yes' if not test_clean else 'no'}",
            f"* live position: {live_state['current_position']}",
            "* live unlocked observations: "
            + str(len(live_state["data"].get("unlocked_observations", []))),
            f"* live response profile: {live_state['response_profile']}",
            (
                "* API budget: "
                f"daily ${usage['daily_cost']:.4f}/${budgets['hard_daily']:.2f}; "
                f"monthly ${usage['monthly_cost']:.4f}/${budgets['hard_monthly']:.2f}"
            ),
            f"* database backup: {backup_text}",
            f"* live mode: {live_state['mode']}",
        ]
        return ReadinessReport(ready, "\n".join(lines), checks)

    async def start_live(self, actor_user_id: int, *, confirm: bool) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Live launch cancelled; set confirm to true.")
        report = await self.live_readiness()
        if not report.ready:
            return PublicResult(False, report.text)
        snapshot = await self.sessions.start(Environment.LIVE, actor_id=f"discord:{actor_user_id}")
        return PublicResult(
            True,
            f"Live session launched from a clean Position 0 state: {snapshot.mode.value}.",
        )

    async def rollback(
        self, environment: Environment, event_id: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Rollback cancelled; set confirm to true.")
        ref = self.refs[environment]
        if (await self.repository.state(ref))["mode"] != SessionMode.PAUSED.value:
            raise StorageError("pause the session before rollback")
        result = await self.repository.rollback_to_event(ref, event_id, f"discord:{actor_user_id}")
        return PublicResult(
            result.accepted,
            f"{environment.value.title()} restored through event `{event_id}`.",
            result.event_id,
        )

    async def invalidate(
        self, environment: Environment, event_id: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Invalidation cancelled; set confirm to true.")
        result = await self.repository.invalidate_event(
            self.refs[environment], event_id, f"discord:{actor_user_id}"
        )
        return PublicResult(
            result.accepted,
            f"Event `{event_id}` invalidated; the session remains paused at its prior state.",
            result.event_id,
        )

    async def retry_event(
        self, environment: Environment, event_id: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Retry cancelled; set confirm to true.")
        ref = self.refs[environment]
        event = await self.repository.event(ref, event_id)
        if event is None:
            raise StorageError("event does not exist in this session")
        if event["invalidated_by_event_id"] is None:
            raise StorageError("invalidate the event before retrying it")
        try:
            action = TypeAdapter(CandidateAction).validate_python(event["payload"]["action"])
        except (KeyError, ValidationError) as exc:
            raise StorageError("event does not contain a retryable typed action") from exc
        outcome = await self.game.engine.process(
            ref,
            participant_id=str(event["actor_id"]),
            action=action,
            idempotency_key=f"retry:{event_id}",
        )
        return await self.game.render_outcome(ref, str(event["actor_id"]), outcome)

    async def debug_state(self, environment: Environment) -> str:
        state = await self.repository.state(self.refs[environment])
        data = state["data"]
        control = await self.repository.runtime_control(self.refs[environment])
        return (
            f"environment={environment.value} mode={state['mode']} "
            f"position={state['current_position']} profile={state['response_profile']} "
            f"version={state['version']} modified={state['modified_by_force']} "
            f"unlocked_count={len(data.get('unlocked_observations', []))} "
            f"contribution_count={len(data.get('contributions', []))} "
            f"proposal_count={len(data.get('proposals', {}))} "
            f"fallback={control['fallback_mode']} "
            f"api_failures={control['consecutive_api_failures']}"
        )

    async def export(self, environment: Environment) -> str:
        return await self.repository.export_json(self.refs[environment])

    async def test_checkpoint(self, name: str, actor_user_id: int) -> PublicResult:
        normalized = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", normalized):
            raise StorageError("checkpoint name must be 1-64 safe letters, digits, or separators")
        checkpoint_id = await self.repository.create_checkpoint(
            self.refs[Environment.TEST], normalized, f"discord:{actor_user_id}"
        )
        return PublicResult(
            True, f"Test checkpoint `{normalized}` created: `{checkpoint_id}`.", checkpoint_id
        )

    async def test_rollback_checkpoint(
        self, checkpoint_id: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Checkpoint rollback cancelled; set confirm to true.")
        ref = self.refs[Environment.TEST]
        if (await self.repository.state(ref))["mode"] != SessionMode.PAUSED.value:
            raise StorageError("pause the test session before checkpoint rollback")
        result = await self.repository.rollback_to_checkpoint(
            ref, checkpoint_id, f"discord:{actor_user_id}"
        )
        return PublicResult(
            result.accepted,
            f"Test state restored from checkpoint `{checkpoint_id}`; event history was preserved.",
            result.event_id,
        )

    async def import_test(
        self, document: dict[str, Any], actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Test import cancelled; set confirm to true.")
        ref = self.refs[Environment.TEST]
        if (await self.repository.state(ref))["mode"] != SessionMode.PAUSED.value:
            raise StorageError("pause the test session before importing state")
        result = await self.repository.import_state(
            ref,
            document,
            f"discord:{actor_user_id}",
            allow_cross_environment=False,
        )
        return PublicResult(
            result.accepted,
            "Test export imported and marked modified; live state was not accessed.",
            result.event_id,
        )

    async def clear_test_history(self, actor_user_id: int, *, confirm: bool) -> PublicResult:
        if not confirm:
            return PublicResult(False, "History clearing cancelled; set confirm to true.")
        await self.repository.clear_generated_history(
            self.refs[Environment.TEST], f"discord:{actor_user_id}"
        )
        return PublicResult(
            True,
            "Test generated narration history cleared; durable events remain.",
        )

    async def force_test_event(
        self, label: str, note: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Forced event cancelled; set confirm to true.")
        result = await self.repository.force_test_event(
            self.refs[Environment.TEST],
            label=label,
            note=note,
            actor_id=f"discord:{actor_user_id}",
        )
        return PublicResult(
            result.accepted,
            f"FORCED TEST EVENT `{label}` recorded. Test session marked modified.",
            result.event_id,
        )

    async def set_test_position(
        self, position: int, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Position override cancelled; set confirm to true.")
        definition = self.game.registries[Environment.TEST].get(position)
        result = await self.repository.force_set_position(
            self.refs[Environment.TEST],
            position=position,
            initial_data=definition.initial_state(),
            actor_id=f"discord:{actor_user_id}",
        )
        return PublicResult(
            result.accepted,
            f"Test position forced to {position} ({definition.title}); session marked modified.",
            result.event_id,
        )

    async def set_test_profile(
        self, profile: str, actor_user_id: int, *, confirm: bool
    ) -> PublicResult:
        if not confirm:
            return PublicResult(False, "Profile override cancelled; set confirm to true.")
        normalized = profile.strip().lower()
        available = self.game.narrators[Environment.TEST].templates
        if normalized not in available:
            raise StorageError("profile is not backed by deterministic narration templates")
        result = await self.repository.force_set_profile(
            self.refs[Environment.TEST],
            profile=normalized,
            actor_id=f"discord:{actor_user_id}",
        )
        return PublicResult(
            result.accepted,
            f"Test response profile forced to `{normalized}`; session marked modified.",
            result.event_id,
        )

    async def set_test_gpt(self, enabled: bool, actor_user_id: int) -> PublicResult:
        ref = self.refs[Environment.TEST]
        actor_id = f"discord:{actor_user_id}"
        await self.repository.update_runtime_control(
            ref, actor_id, feature_flag=("natural_language", enabled)
        )
        await self.repository.update_runtime_control(
            ref, actor_id, feature_flag=("gpt_narration", enabled)
        )
        return PublicResult(
            True,
            (
                "Test GPT feature gates are enabled; startup API configuration and fallback "
                "mode still apply."
                if enabled
                else "Test GPT interpretation and narration feature gates are disabled."
            ),
        )

    async def set_model(
        self, environment: Environment, purpose: str, model: str, actor_user_id: int
    ) -> PublicResult:
        kwargs = (
            {"interpretation_model": model}
            if purpose == "interpretation"
            else {"narration_model": model}
            if purpose == "narration"
            else None
        )
        if kwargs is None:
            return PublicResult(False, "Purpose must be interpretation or narration.")
        control = await self.repository.update_runtime_control(
            self.refs[environment], f"discord:{actor_user_id}", **kwargs
        )
        selected = str(control[f"{purpose}_model"])
        return PublicResult(True, f"{purpose.title()} model set to `{selected}` for {environment}.")

    async def set_api_budget(
        self,
        environment: Environment,
        period: str,
        soft: float,
        hard: float,
        actor_user_id: int,
    ) -> PublicResult:
        if period not in {"daily", "monthly"}:
            return PublicResult(False, "Period must be daily or monthly.")
        control = await self.repository.update_runtime_control(
            self.refs[environment],
            f"discord:{actor_user_id}",
            budget_overrides={f"soft_{period}": soft, f"hard_{period}": hard},
        )
        values = control["budget_overrides"]
        return PublicResult(
            True,
            f"{environment.value.title()} {period} API budget: "
            f"soft ${values[f'soft_{period}']:.2f}; hard ${values[f'hard_{period}']:.2f}.",
        )

    async def fallback_mode(
        self, environment: Environment, enabled: bool, actor_user_id: int
    ) -> PublicResult:
        await self.repository.update_runtime_control(
            self.refs[environment],
            f"discord:{actor_user_id}",
            fallback_mode=enabled,
        )
        return PublicResult(
            True,
            f"{environment.value.title()} deterministic fallback mode is "
            f"{'enabled' if enabled else 'disabled'}.",
        )

    async def set_feature(
        self, environment: Environment, name: str, enabled: bool, actor_user_id: int
    ) -> PublicResult:
        await self.repository.update_runtime_control(
            self.refs[environment],
            f"discord:{actor_user_id}",
            feature_flag=(name, enabled),
        )
        return PublicResult(
            True,
            f"{environment.value.title()} feature `{name}` is "
            f"{'enabled' if enabled else 'disabled'}.",
        )

    def _effective_budgets(self, control: dict[str, Any]) -> dict[str, float]:
        return {
            "soft_daily": float(
                control["budget_overrides"].get(
                    "soft_daily", self.settings.openai_soft_daily_budget_usd
                )
            ),
            "hard_daily": float(
                control["budget_overrides"].get(
                    "hard_daily", self.settings.openai_hard_daily_budget_usd
                )
            ),
            "soft_monthly": float(
                control["budget_overrides"].get(
                    "soft_monthly", self.settings.openai_soft_monthly_budget_usd
                )
            ),
            "hard_monthly": float(
                control["budget_overrides"].get(
                    "hard_monthly", self.settings.openai_hard_monthly_budget_usd
                )
            ),
        }

    @staticmethod
    def _mark(value: bool) -> str:
        return "yes" if value else "no"
