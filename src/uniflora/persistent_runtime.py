from __future__ import annotations

import asyncio

from uniflora.runtime import (
    Environment,
    InvalidTransition,
    RoutingSnapshot,
    RuntimeRouting,
    SessionMode,
    SessionSnapshot,
)
from uniflora.storage.repository import GameRepository, SessionRef


class PersistentRuntimeSessions:
    def __init__(self, repository: GameRepository, refs: dict[Environment, SessionRef]) -> None:
        self.repository = repository
        self.refs = refs
        self._locks = {environment: asyncio.Lock() for environment in Environment}

    async def snapshot(self, environment: Environment) -> SessionSnapshot:
        return await self.repository.session_snapshot(self.refs[environment])

    async def all_snapshots(self) -> dict[str, dict[str, str]]:
        snapshots = await asyncio.gather(*(self.snapshot(item) for item in Environment))
        return {snapshot.environment.value: snapshot.health_dict() for snapshot in snapshots}

    async def start(self, environment: Environment, actor_id: str | None = None) -> SessionSnapshot:
        return await self._transition(
            environment, SessionMode.RUNNING, {SessionMode.LOCKED}, actor_id
        )

    async def pause(self, environment: Environment, actor_id: str | None = None) -> SessionSnapshot:
        return await self._transition(
            environment, SessionMode.PAUSED, {SessionMode.RUNNING}, actor_id
        )

    async def resume(
        self, environment: Environment, actor_id: str | None = None
    ) -> SessionSnapshot:
        return await self._transition(
            environment, SessionMode.RUNNING, {SessionMode.PAUSED}, actor_id
        )

    async def _transition(
        self,
        environment: Environment,
        target: SessionMode,
        allowed_from: set[SessionMode],
        actor_id: str | None,
    ) -> SessionSnapshot:
        async with self._locks[environment]:
            result = await self.repository.transition(
                self.refs[environment],
                target,
                allowed_from,
                actor_id=actor_id or "system:discord-command",
            )
            if not result.accepted:
                current = await self.snapshot(environment)
                raise InvalidTransition(
                    f"cannot move {environment.value} from {current.mode.value} to {target.value}"
                )
            return await self.snapshot(environment)


class PersistentRouting(RuntimeRouting):
    def __init__(self, initial: RoutingSnapshot, repository: GameRepository) -> None:
        super().__init__(initial)
        self.repository = repository

    async def set_live_channel(self, channel_id: int) -> RoutingSnapshot:
        async with self._lock:
            value = await self.repository.update_routing(
                self._value.guild_id, live_channel_id=channel_id
            )
            self._value = value
            return value

    async def set_test_channel(self, channel_id: int) -> RoutingSnapshot:
        async with self._lock:
            value = await self.repository.update_routing(
                self._value.guild_id, test_channel_id=channel_id
            )
            self._value = value
            return value

    async def set_role(self, role_id: int) -> RoutingSnapshot:
        async with self._lock:
            value = await self.repository.update_routing(self._value.guild_id, role_id=role_id)
            self._value = value
            return value

    async def set_diagnostic_channel(self, channel_id: int | None) -> RoutingSnapshot:
        async with self._lock:
            value = await self.repository.update_routing(
                self._value.guild_id, diagnostic_channel_id=channel_id
            )
            self._value = value
            return value
