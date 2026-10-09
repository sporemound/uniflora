from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum


class Environment(StrEnum):
    LIVE = "live"
    TEST = "test"


class SessionMode(StrEnum):
    LOCKED = "locked"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    environment: Environment
    mode: SessionMode
    updated_at: str

    def health_dict(self) -> dict[str, str]:
        result = asdict(self)
        result["environment"] = self.environment.value
        result["mode"] = self.mode.value
        return result


class InvalidTransition(ValueError):
    pass


class RuntimeSessions:
    """In-memory adapter retained for isolated unit tests."""

    def __init__(self) -> None:
        now = datetime.now(UTC).isoformat()
        self._states = {
            Environment.LIVE: SessionSnapshot(Environment.LIVE, SessionMode.LOCKED, now),
            Environment.TEST: SessionSnapshot(Environment.TEST, SessionMode.LOCKED, now),
        }
        self._lock = asyncio.Lock()

    async def snapshot(self, environment: Environment) -> SessionSnapshot:
        async with self._lock:
            return self._states[environment]

    async def all_snapshots(self) -> dict[str, dict[str, str]]:
        async with self._lock:
            return {key.value: value.health_dict() for key, value in self._states.items()}

    async def start(self, environment: Environment, actor_id: str | None = None) -> SessionSnapshot:
        del actor_id
        return await self._transition(environment, SessionMode.RUNNING, {SessionMode.LOCKED})

    async def pause(self, environment: Environment, actor_id: str | None = None) -> SessionSnapshot:
        del actor_id
        return await self._transition(environment, SessionMode.PAUSED, {SessionMode.RUNNING})

    async def resume(
        self, environment: Environment, actor_id: str | None = None
    ) -> SessionSnapshot:
        del actor_id
        return await self._transition(environment, SessionMode.RUNNING, {SessionMode.PAUSED})

    async def _transition(
        self,
        environment: Environment,
        target: SessionMode,
        allowed_from: set[SessionMode],
    ) -> SessionSnapshot:
        async with self._lock:
            current = self._states[environment]
            if current.mode is target:
                return current
            if current.mode not in allowed_from:
                raise InvalidTransition(
                    f"cannot move {environment.value} from {current.mode.value} to {target.value}"
                )
            updated = SessionSnapshot(environment, target, datetime.now(UTC).isoformat())
            self._states[environment] = updated
            return updated


@dataclass(frozen=True, slots=True)
class RoutingSnapshot:
    guild_id: int
    live_channel_id: int
    test_channel_id: int
    mycotroph_role_id: int
    admin_user_ids: frozenset[int]
    diagnostic_channel_id: int | None = None


class RuntimeRouting:
    """Mutable routing base used by in-memory tests and persistent production routing."""

    def __init__(self, initial: RoutingSnapshot) -> None:
        self._value = initial
        self._lock = asyncio.Lock()

    @property
    def current(self) -> RoutingSnapshot:
        return self._value

    async def set_live_channel(self, channel_id: int) -> RoutingSnapshot:
        async with self._lock:
            if channel_id in {
                self._value.test_channel_id,
                self._value.diagnostic_channel_id,
            }:
                raise ValueError("live, test, and diagnostic channels must remain distinct")
            self._value = RoutingSnapshot(
                self._value.guild_id,
                channel_id,
                self._value.test_channel_id,
                self._value.mycotroph_role_id,
                self._value.admin_user_ids,
                self._value.diagnostic_channel_id,
            )
            return self._value

    async def set_test_channel(self, channel_id: int) -> RoutingSnapshot:
        async with self._lock:
            if channel_id in {
                self._value.live_channel_id,
                self._value.diagnostic_channel_id,
            }:
                raise ValueError("live, test, and diagnostic channels must remain distinct")
            self._value = RoutingSnapshot(
                self._value.guild_id,
                self._value.live_channel_id,
                channel_id,
                self._value.mycotroph_role_id,
                self._value.admin_user_ids,
                self._value.diagnostic_channel_id,
            )
            return self._value

    async def set_role(self, role_id: int) -> RoutingSnapshot:
        async with self._lock:
            self._value = RoutingSnapshot(
                self._value.guild_id,
                self._value.live_channel_id,
                self._value.test_channel_id,
                role_id,
                self._value.admin_user_ids,
                self._value.diagnostic_channel_id,
            )
            return self._value

    async def set_diagnostic_channel(self, channel_id: int | None) -> RoutingSnapshot:
        async with self._lock:
            if channel_id in {self._value.live_channel_id, self._value.test_channel_id}:
                raise ValueError("diagnostic channel must be distinct from puzzle channels")
            self._value = RoutingSnapshot(
                self._value.guild_id,
                self._value.live_channel_id,
                self._value.test_channel_id,
                self._value.mycotroph_role_id,
                self._value.admin_user_ids,
                channel_id,
            )
            return self._value
