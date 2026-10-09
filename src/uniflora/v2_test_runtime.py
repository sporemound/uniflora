from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Final

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack
from uniflora.engine.v2.application import (
    V2ApplicationCommandResult,
    V2PersistentInvestigationService,
    V2SessionView,
)
from uniflora.engine.v2.commands import (
    V2AssignRoleCommand,
    V2InvestigationCommand,
    V2JoinInvestigationCommand,
)
from uniflora.engine.v2.delivery import (
    build_position_guide,
    guided_suggestions,
)
from uniflora.engine.v2.persistence import V2SQLiteEventStore
from uniflora.engine.v2.rendering import (
    V2RenderedResponse,
    render_application_result,
    render_session_view,
)
from uniflora.engine.v2.state import V2InvestigationState
from uniflora.engine.v2.transport import V2TextCommandAdapter
from uniflora.engine.v2.transport_facade import (
    V2TransportFacade,
    V2TransportResponse,
)


class V2TestRuntimeError(RuntimeError):
    """Raised when the bounded v2 test runtime cannot safely proceed."""


class UnknownV2TestIdentityError(V2TestRuntimeError):
    """Raised when a command names an identity outside the fixed test roster."""


class ClosedV2TestRuntimeError(V2TestRuntimeError):
    """Raised when work is requested after the runtime has closed."""


V2_TEST_IDENTITIES: Final = MappingProxyType(
    {
        "investigator-a": "test:investigator-a",
        "reviewer-b": "test:reviewer-b",
    }
)


class V2TestRuntime:
    """Persistent, serialized access to one canonical v2 test stream.

    The runtime preserves the two fixed identities for automated tests while
    also allowing authenticated web participants to join the event-sourced
    stream under stable ``web:<participant-id>`` identities.
    """

    def __init__(
        self, database: str | Path, *, stream_id: str,
        initial_player_ids: tuple[str, ...] | None = None,
        pack: V2InvestigationPack | None = None,
    ) -> None:
        normalized_stream_id = stream_id.strip()
        if not normalized_stream_id:
            raise ValueError("v2 test stream ID must not be blank")

        self.stream_id = normalized_stream_id
        self._initial_player_ids = (
            tuple(V2_TEST_IDENTITIES.values())
            if initial_player_ids is None else initial_player_ids
        )
        if len(set(self._initial_player_ids)) != len(self._initial_player_ids):
            raise ValueError("initial v2 players must be distinct")
        self._lock = asyncio.Lock()
        self._closed = False
        self._store = V2SQLiteEventStore(database)
        self._pack = pack or load_missing_interior_pack()
        service = V2PersistentInvestigationService(
            self._pack,
            self._store,
        )
        self._service = service
        self._transport = V2TransportFacade(V2TextCommandAdapter(service))

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(V2_TEST_IDENTITIES)

    @property
    def pack(self) -> V2InvestigationPack:
        return self._pack

    def _require_open(self) -> None:
        if self._closed:
            raise ClosedV2TestRuntimeError("v2 test runtime is closed")

    def _player_id(self, identity: str) -> str:
        normalized = identity.strip().casefold()
        try:
            return V2_TEST_IDENTITIES[normalized]
        except KeyError as exc:
            allowed = ", ".join(V2_TEST_IDENTITIES)
            raise UnknownV2TestIdentityError(
                f"unknown v2 test identity {identity!r}; choose one of: {allowed}"
            ) from exc

    def _ensure_session(self) -> V2SessionView:
        if self._store.latest_sequence(self.stream_id) is None:
            if not self._initial_player_ids:
                raise V2TestRuntimeError("the web investigation has no enrolled players yet")
            self._service.create_session(
                self.stream_id,
                self._initial_player_ids,
            )

        return self._service.load_session(self.stream_id)

    def _ensure_public_player_locked(self, player_id: str) -> V2SessionView:
        normalized = player_id.strip()
        if not any(
            normalized.startswith(prefix) and len(normalized) > len(prefix)
            for prefix in ("discord:", "web:")
        ):
            raise V2TestRuntimeError("public v2 player IDs must use discord: or web: identities")

        if self._store.latest_sequence(self.stream_id) is None and not self._initial_player_ids:
            self._service.create_session(self.stream_id, (normalized,))
        session = self._ensure_session()
        if session.state.get_player(normalized) is not None:
            return session

        result = self._service.execute(
            self.stream_id,
            V2JoinInvestigationCommand(player_id=normalized),
            expected_sequence=session.sequence,
        )
        if not result.accepted:
            raise V2TestRuntimeError(result.message)
        return result.session

    def _wrap_application_result(
        self,
        result: V2ApplicationCommandResult,
        *,
        command: V2InvestigationCommand,
        previous_state: V2InvestigationState,
    ) -> V2TransportResponse:
        return V2TransportResponse(
            route="investigation",
            payload=render_application_result(
                result,
                pack=self._pack,
                command=command,
                previous_state=previous_state,
            ),
        )

    async def public_status(
        self,
        *,
        player_id: str | None = None,
    ) -> V2TransportResponse:
        """Render compact shared state for the requesting participant."""

        async with self._lock:
            self._require_open()
            normalized_player_id = (
                player_id.strip()
                if player_id is not None
                else None
            )
            session = (
                self._ensure_public_player_locked(normalized_player_id)
                if normalized_player_id is not None and normalized_player_id.startswith("web:")
                else self._ensure_session()
            )
            return V2TransportResponse(
                route="investigation",
                payload=render_session_view(
                    session,
                    pack=self._pack,
                    player_id=normalized_player_id,
                ),
            )

    async def execute_public(
        self,
        *,
        player_id: str,
        text: str,
    ) -> V2TransportResponse:
        """Execute one strict command as the authenticated participant."""

        async with self._lock:
            self._require_open()
            normalized = player_id.strip()
            session = self._ensure_public_player_locked(normalized)
            payload = V2TextCommandAdapter(self._service).execute(
                self.stream_id,
                player_id=normalized,
                text=text,
                expected_sequence=session.sequence,
            )
            return V2TransportResponse(
                route="investigation",
                payload=payload,
            )

    async def assign_public_role(
        self,
        *,
        player_id: str,
        role_id: str,
        display_name: str | None = None,
        description: str | None = None,
    ) -> V2TransportResponse:
        """Assign a canonical role with optional player-authored display text."""

        async with self._lock:
            self._require_open()
            session = self._ensure_public_player_locked(player_id)

            command = V2AssignRoleCommand(
                player_id=player_id.strip(),
                role_id=role_id,
                display_name=display_name,
                description=description,
            )

            result = self._service.execute(
                self.stream_id,
                command,
                expected_sequence=session.sequence,
            )

            return self._wrap_application_result(
                result,
                command=command,
                previous_state=session.state,
            )

    
    async def available_public_roles(
        self,
        current: str = "",
    ) -> tuple[tuple[str, str], ...]:
        """Return every canonical role available for the current position."""

        async with self._lock:
            self._require_open()
            session = self._ensure_session()
            state = session.state
            needle = current.strip().casefold()

            position = next(
                (
                    item
                    for item in self._pack.positions
                    if item.id == state.current_position_id
                ),
                None,
            )

            if position is None:
                return ()

            focus_location_id = position.focus_location_id

            roles = [
                role
                for role in self._pack.roles
                if (
                    not role.allowed_location_ids
                    or focus_location_id in role.allowed_location_ids
                )
                and (
                    not needle
                    or needle in role.id.casefold()
                    or needle in role.name.casefold()
                    or needle in role.description.casefold()
                )
            ]

            roles.sort(
                key=lambda role: (
                    role.name.casefold(),
                    role.id.casefold(),
                )
            )

            return tuple(
                (
                    role.id,
                    f"{role.name} — {role.description}"[:100],
                )
                for role in roles[:25]
            )

    async def available_public_commands(
        self,
        *,
        player_id: str,
        current: str = "",
    ) -> tuple[tuple[str, str], ...]:
        async with self._lock:
            self._require_open()

            normalized = player_id.strip()
            session = self._ensure_public_player_locked(normalized)

            suggestions = guided_suggestions(
                self._pack,
                session.state,
                normalized,
                current,
            )

            return tuple(
                (
                    suggestion.command,
                    suggestion.label[:100],
                )
                for suggestion in suggestions
                if len(suggestion.command) <= 100
            )

    async def public_guide(
        self,
        *,
        player_id: str,
    ) -> str:
        async with self._lock:
            self._require_open()

            normalized = player_id.strip()
            session = self._ensure_public_player_locked(normalized)

            return build_position_guide(
                self._pack,
                session.state,
                normalized,
            )

    async def session(self) -> V2SessionView:
        """Create the configured stream if needed, then return verified state."""

        async with self._lock:
            self._require_open()
            return self._ensure_session()

    async def status(self) -> V2TransportResponse:
        """Render verified state for the configured stream."""

        async with self._lock:
            self._require_open()
            self._ensure_session()
            return self._transport.render_session(self.stream_id)

    async def execute(self, *, identity: str, text: str) -> V2TransportResponse:
        """Execute one strict command as a fixed simulated test identity."""

        player_id = self._player_id(identity)
        async with self._lock:
            self._require_open()
            session = self._ensure_session()
            response = self._transport.execute(
                self.stream_id,
                player_id=player_id,
                text=text,
                expected_sequence=session.sequence,
            )
            if response.accepted and response.code in {
                "investigation_begun",
                "position_completed",
            }:
                updated = self._ensure_session()
                presentation_details = self._resolved_presentation_details(updated)
                if presentation_details and isinstance(response.payload, V2RenderedResponse):
                    response = replace(
                        response,
                        payload=replace(
                            response.payload,
                            details=response.payload.details + presentation_details,
                        ),
                    )
            return response

    def _resolved_presentation_details(
        self,
        session: V2SessionView,
    ) -> tuple[str, ...]:
        current_position = next(
            (
                item
                for item in self._pack.positions
                if item.id == session.state.current_position_id
            ),
            None,
        )
        if (
            current_position is not None
            and current_position.fixed_opening is not None
            and current_position.id not in session.state.completed_position_ids
        ):
            details = [current_position.fixed_opening.prologue]
            details.extend(
                f"Working control: {item}"
                for item in current_position.fixed_opening.guidance
            )
            return tuple(details)
        if not session.state.adaptation_selections:
            return ()
        selection = session.state.adaptation_selections[-1]
        if selection.target_id == "ending":
            if self._pack.endings is None:
                return ()
            candidate = next(
                (
                    item
                    for item in (
                        self._pack.endings.corrective,
                        self._pack.endings.baseline,
                        self._pack.endings.advanced,
                    )
                    if item.presentation_id == selection.presentation_id
                ),
                None,
            )
            return (candidate.prose,) if candidate is not None else ()

        position = next(
            (item for item in self._pack.positions if item.id == selection.target_id),
            None,
        )
        if position is None or position.adaptation is None:
            return ()
        candidate = next(
            (
                item
                for item in (
                    position.adaptation.corrective,
                    position.adaptation.baseline,
                    position.adaptation.advanced,
                )
                if item.presentation_id == selection.presentation_id
            ),
            None,
        )
        if candidate is None:
            return ()
        details = [candidate.prologue]
        details.extend(f"Working control: {item}" for item in candidate.guidance)
        if candidate.required_action_id is not None:
            details.append(f"Required reconciliation: {candidate.required_action_id}")
        if candidate.optional_action_ids:
            details.append("Optional analysis: " + ", ".join(candidate.optional_action_ids))
        return tuple(details)

    async def close(self) -> None:
        """Close the SQLite event store; repeated calls are harmless."""

        async with self._lock:
            if self._closed:
                return
            self._store.close()
            self._closed = True
