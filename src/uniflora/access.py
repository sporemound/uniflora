from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from uniflora.runtime import Environment, RoutingSnapshot, SessionMode


class AccessResult(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class RequestContext:
    guild_id: int | None
    channel_id: int | None
    user_id: int
    role_ids: frozenset[int] = frozenset()
    is_dm: bool = False
    thread_parent_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    result: AccessResult
    environment: Environment | None = None
    reason: str = ""


class AccessPolicy:
    """Central public-surface authorization policy, independent from discord.py."""

    def resolve_environment(
        self, context: RequestContext, routing: RoutingSnapshot
    ) -> Environment | None:
        if context.is_dm or context.guild_id is None or context.channel_id is None:
            return None
        if context.guild_id != routing.guild_id:
            return None
        channel_id = context.thread_parent_channel_id or context.channel_id
        if channel_id == routing.live_channel_id:
            return Environment.LIVE
        if channel_id == routing.test_channel_id:
            return Environment.TEST
        return None

    def authorize_admin(
        self,
        context: RequestContext,
        routing: RoutingSnapshot,
        required_environment: Environment | None = None,
    ) -> AccessDecision:
        environment = self.resolve_environment(context, routing)
        if environment is None:
            return AccessDecision(AccessResult.IGNORED, reason="outside configured surfaces")
        if required_environment is not None and environment is not required_environment:
            return AccessDecision(AccessResult.DENIED, environment, "wrong operating surface")
        if context.user_id not in routing.admin_user_ids:
            return AccessDecision(
                AccessResult.DENIED, environment, "configured administrator required"
            )
        return AccessDecision(AccessResult.ALLOWED, environment)

    def authorize_diagnostic(
        self, context: RequestContext, routing: RoutingSnapshot
    ) -> AccessDecision:
        if context.is_dm or context.guild_id != routing.guild_id:
            return AccessDecision(AccessResult.IGNORED, reason="outside configured guild")
        if routing.diagnostic_channel_id is None or (
            context.channel_id != routing.diagnostic_channel_id
        ):
            return AccessDecision(AccessResult.DENIED, reason="diagnostic channel required")
        if context.user_id not in routing.admin_user_ids:
            return AccessDecision(AccessResult.DENIED, reason="configured administrator required")
        return AccessDecision(AccessResult.ALLOWED)

    def authorize_player(
        self,
        context: RequestContext,
        routing: RoutingSnapshot,
        modes: dict[Environment, SessionMode],
    ) -> AccessDecision:
        environment = self.resolve_environment(context, routing)
        if environment is None:
            return AccessDecision(AccessResult.IGNORED, reason="outside configured surfaces")
        is_admin = context.user_id in routing.admin_user_ids
        if environment is Environment.TEST:
            if not is_admin:
                return AccessDecision(
                    AccessResult.DENIED, environment, "test is administrator-only"
                )
        elif not is_admin and routing.mycotroph_role_id not in context.role_ids:
            return AccessDecision(AccessResult.DENIED, environment, "mycotroph role required")
        if modes[environment] is not SessionMode.RUNNING:
            return AccessDecision(AccessResult.DENIED, environment, "session is not running")
        return AccessDecision(AccessResult.ALLOWED, environment)

    def authorize_difficulty_selection(
        self,
        context: RequestContext,
        routing: RoutingSnapshot,
        required_environment: Environment | None = None,
    ) -> AccessDecision:
        """Authorize a private pre-game presentation preference.

        Difficulty selection is available while a session is locked or paused, but
        it retains the exact guild, channel, administrator, and player-role checks
        used by the configured game surfaces.
        """

        environment = self.resolve_environment(context, routing)
        if environment is None:
            return AccessDecision(AccessResult.IGNORED, reason="outside configured surfaces")
        if required_environment is not None and environment is not required_environment:
            return AccessDecision(AccessResult.DENIED, environment, "wrong operating surface")
        is_admin = context.user_id in routing.admin_user_ids
        if environment is Environment.TEST:
            if not is_admin:
                return AccessDecision(
                    AccessResult.DENIED,
                    environment,
                    "test is administrator-only",
                )
        elif not is_admin and routing.mycotroph_role_id not in context.role_ids:
            return AccessDecision(
                AccessResult.DENIED,
                environment,
                "mycotroph role required",
            )
        return AccessDecision(AccessResult.ALLOWED, environment)
