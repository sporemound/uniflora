from __future__ import annotations

from dataclasses import replace

import pytest

from uniflora.access import AccessPolicy, AccessResult, RequestContext
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode


@pytest.fixture
def routing() -> RoutingSnapshot:
    return RoutingSnapshot(
        guild_id=1,
        live_channel_id=10,
        test_channel_id=20,
        mycotroph_role_id=30,
        admin_user_ids=frozenset({99}),
    )


@pytest.fixture
def modes() -> dict[Environment, SessionMode]:
    return {Environment.LIVE: SessionMode.RUNNING, Environment.TEST: SessionMode.RUNNING}


def context(
    *,
    channel: int | None,
    user: int = 5,
    roles: frozenset[int] = frozenset(),
    guild: int | None = 1,
) -> RequestContext:
    return RequestContext(
        guild_id=guild,
        channel_id=channel,
        user_id=user,
        role_ids=roles,
        is_dm=guild is None,
    )


def test_dm_is_ignored(routing: RoutingSnapshot, modes: dict[Environment, SessionMode]) -> None:
    result = AccessPolicy().authorize_player(context(channel=None, guild=None), routing, modes)
    assert result.result is AccessResult.IGNORED
    assert result.environment is None


@pytest.mark.parametrize("channel,guild", [(999, 1), (10, 2), (20, 2)])
def test_other_channels_and_guilds_are_ignored(
    routing: RoutingSnapshot,
    modes: dict[Environment, SessionMode],
    channel: int,
    guild: int,
) -> None:
    result = AccessPolicy().authorize_player(context(channel=channel, guild=guild), routing, modes)
    assert result.result is AccessResult.IGNORED


def test_threads_under_configured_channels_inherit_their_environment(
    routing: RoutingSnapshot, modes: dict[Environment, SessionMode]
) -> None:
    policy = AccessPolicy()
    live = replace(
        context(channel=101, roles=frozenset({30})), thread_parent_channel_id=10
    )
    test = replace(context(channel=201, user=99), thread_parent_channel_id=20)
    assert policy.authorize_player(live, routing, modes).environment is Environment.LIVE
    assert policy.authorize_player(test, routing, modes).environment is Environment.TEST
    assert policy.authorize_player(test, routing, modes).result is AccessResult.ALLOWED


def test_thread_parent_does_not_bypass_guild_role_or_surface_checks(
    routing: RoutingSnapshot, modes: dict[Environment, SessionMode]
) -> None:
    policy = AccessPolicy()
    assert policy.authorize_player(
        replace(context(channel=101), thread_parent_channel_id=10), routing, modes
    ).result is AccessResult.DENIED
    assert policy.authorize_player(
        replace(context(channel=101, user=99, guild=2), thread_parent_channel_id=10),
        routing,
        modes,
    ).result is AccessResult.IGNORED
    assert policy.authorize_player(
        replace(context(channel=101, user=99), thread_parent_channel_id=999),
        routing,
        modes,
    ).result is AccessResult.IGNORED
    assert policy.authorize_admin(
        replace(context(channel=101, user=99), thread_parent_channel_id=10),
        routing,
        Environment.TEST,
    ).result is AccessResult.DENIED


def test_live_requires_mycotroph_role(
    routing: RoutingSnapshot, modes: dict[Environment, SessionMode]
) -> None:
    denied = AccessPolicy().authorize_player(context(channel=10), routing, modes)
    allowed = AccessPolicy().authorize_player(
        context(channel=10, roles=frozenset({30})), routing, modes
    )
    assert denied.result is AccessResult.DENIED
    assert allowed.result is AccessResult.ALLOWED
    assert allowed.environment is Environment.LIVE


def test_configured_admin_can_play_live_without_role(
    routing: RoutingSnapshot, modes: dict[Environment, SessionMode]
) -> None:
    result = AccessPolicy().authorize_player(context(channel=10, user=99), routing, modes)
    assert result.result is AccessResult.ALLOWED


def test_test_channel_is_configured_admin_only(
    routing: RoutingSnapshot, modes: dict[Environment, SessionMode]
) -> None:
    role_holder = AccessPolicy().authorize_player(
        context(channel=20, roles=frozenset({30})), routing, modes
    )
    admin = AccessPolicy().authorize_player(context(channel=20, user=99), routing, modes)
    assert role_holder.result is AccessResult.DENIED
    assert admin.result is AccessResult.ALLOWED
    assert admin.environment is Environment.TEST


@pytest.mark.parametrize("environment", [Environment.LIVE, Environment.TEST])
@pytest.mark.parametrize("mode", [SessionMode.LOCKED, SessionMode.PAUSED])
def test_game_actions_require_running_session(
    routing: RoutingSnapshot,
    modes: dict[Environment, SessionMode],
    environment: Environment,
    mode: SessionMode,
) -> None:
    modes[environment] = mode
    channel = 10 if environment is Environment.LIVE else 20
    result = AccessPolicy().authorize_player(context(channel=channel, user=99), routing, modes)
    assert result.result is AccessResult.DENIED


def test_test_session_can_run_while_live_is_locked(routing: RoutingSnapshot) -> None:
    modes = {Environment.LIVE: SessionMode.LOCKED, Environment.TEST: SessionMode.RUNNING}
    result = AccessPolicy().authorize_player(context(channel=20, user=99), routing, modes)
    assert result.result is AccessResult.ALLOWED


@pytest.mark.parametrize("mode", [SessionMode.LOCKED, SessionMode.PAUSED])
def test_difficulty_selection_is_available_before_gameplay(
    routing: RoutingSnapshot,
    modes: dict[Environment, SessionMode],
    mode: SessionMode,
) -> None:
    modes[Environment.TEST] = mode
    result = AccessPolicy().authorize_difficulty_selection(
        context(channel=20, user=99),
        routing,
        Environment.TEST,
    )
    assert result.result is AccessResult.ALLOWED
    assert result.environment is Environment.TEST


def test_difficulty_selection_retains_surface_and_role_checks(
    routing: RoutingSnapshot,
) -> None:
    policy = AccessPolicy()
    assert (
        policy.authorize_difficulty_selection(
            context(channel=20, user=5, roles=frozenset({30})),
            routing,
        ).result
        is AccessResult.DENIED
    )
    assert (
        policy.authorize_difficulty_selection(
            context(channel=10, user=5, roles=frozenset({30})),
            routing,
        ).result
        is AccessResult.ALLOWED
    )
    assert (
        policy.authorize_difficulty_selection(
            context(channel=999, user=99),
            routing,
        ).result
        is AccessResult.IGNORED
    )


def test_admin_commands_require_configured_id(routing: RoutingSnapshot) -> None:
    policy = AccessPolicy()
    denied = policy.authorize_admin(context(channel=20), routing, Environment.TEST)
    allowed = policy.authorize_admin(context(channel=20, user=99), routing, Environment.TEST)
    wrong_surface = policy.authorize_admin(context(channel=10, user=99), routing, Environment.TEST)
    assert denied.result is AccessResult.DENIED
    assert allowed.result is AccessResult.ALLOWED
    assert wrong_surface.result is AccessResult.DENIED


def test_diagnostic_channel_is_configured_admin_only(routing: RoutingSnapshot) -> None:
    configured = replace(routing, diagnostic_channel_id=40)
    policy = AccessPolicy()
    assert (
        policy.authorize_diagnostic(context(channel=40, user=99), configured).result
        is AccessResult.ALLOWED
    )
    assert (
        policy.authorize_diagnostic(context(channel=40, user=5), configured).result
        is AccessResult.DENIED
    )
    assert (
        policy.authorize_diagnostic(context(channel=10, user=99), configured).result
        is AccessResult.DENIED
    )
