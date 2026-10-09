from __future__ import annotations

import pytest

from uniflora.runtime import (
    Environment,
    InvalidTransition,
    RoutingSnapshot,
    RuntimeRouting,
    RuntimeSessions,
    SessionMode,
)


@pytest.mark.asyncio
async def test_live_and_test_state_are_independent() -> None:
    sessions = RuntimeSessions()
    await sessions.start(Environment.TEST)
    assert (await sessions.snapshot(Environment.TEST)).mode is SessionMode.RUNNING
    assert (await sessions.snapshot(Environment.LIVE)).mode is SessionMode.LOCKED


@pytest.mark.asyncio
async def test_pause_and_resume_are_explicit_transitions() -> None:
    sessions = RuntimeSessions()
    with pytest.raises(InvalidTransition):
        await sessions.pause(Environment.LIVE)
    await sessions.start(Environment.LIVE)
    await sessions.pause(Environment.LIVE)
    assert (await sessions.snapshot(Environment.LIVE)).mode is SessionMode.PAUSED
    await sessions.resume(Environment.LIVE)
    assert (await sessions.snapshot(Environment.LIVE)).mode is SessionMode.RUNNING


@pytest.mark.asyncio
async def test_routing_refuses_channel_collision() -> None:
    routing = RuntimeRouting(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    with pytest.raises(ValueError, match="distinct"):
        await routing.set_test_channel(10)
    with pytest.raises(ValueError, match="distinct"):
        await routing.set_live_channel(20)
