from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from uniflora.content.v2 import V2InvestigationPack
from uniflora.engine.v2.application import V2SessionView
from uniflora.engine.v2.delivery import (
    action_context_blockers,
    completion_route_progress,
    next_requirement,
    relevant_actions,
    relevant_evidence_ids,
)
from uniflora.engine.v2.strategic import action_profile, preview_strategic_state

_SCHEMA_VERSION = "2.4.0"
_SOURCE = "hypha"
_HYPHA_STATE_PATH = "/api/hypha/state"
_MAX_RESPONSE_BYTES = 1_048_576
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,160}$")

_ROOT_KEYS = frozenset(
    {
        "schemaVersion",
        "source",
        "environment",
        "revision",
        "sequence",
        "stateHeadHash",
        "previousStateHeadHash",
        "positionId",
        "positionTitle",
        "focusLocationId",
        "casePhase",
        "updatedAt",
        "zuluTime",
        "facilityTime",
        "facilityTimezone",
        "metrics",
        "locations",
        "assignments",
        "latestPublication",
        "nextRequirement",
        "positions",
        "adaptivePresentation",
        "contentVersion",
        "evidence",
        "actions",
        "completionRoutes",
        "stochasticProcesses",
        "recentObservations",
        "campaignTracks",
        "strategicBoard",
        "strategicOutcomes",
        "campaignModifiers",
    }
)

_PUBLICATION_KEYS = frozenset(
    {
        "publicationId",
        "artifactId",
        "title",
        "institution",
        "finding",
        "limitation",
        "status",
        "primaryAsset",
        "manifestUrl",
    }
)
_PUBLICATION_ASSET_KEYS = frozenset(
    {
        "filename",
        "contentType",
        "byteLength",
        "sha256",
        "url",
    }
)

_POSITION_CONTRACT = (
    (
        "network_orientation",
        0,
        "The Network Before the Event",
        "boundary_array",
    ),
    ("boundary_event", 1, "First Return", "boundary_array"),
    (
        "aeronautical_incident",
        2,
        "The Track That Will Not Close",
        "aeronautical_incident_center",
    ),
    (
        "archive_convergence",
        3,
        "A Pattern Without a Common Cause",
        "aerial_phenomena_archive",
    ),
    (
        "holographic_reconstruction",
        4,
        "The Volume Defined by Its Absence",
        "holography_laboratory",
    ),
    (
        "subsurface_resonance",
        5,
        "A Mode Without a Source Point",
        "subsurface_resonance_station",
    ),
    (
        "quantum_state",
        6,
        "The View From the Missing Interior",
        "quantum_state_institute",
    ),
)


@dataclass(frozen=True, slots=True)
class _FacilityMetadata:
    short_name: str
    timezone: str
    timezone_label: str


_FACILITY_METADATA = {
    "boundary_array": _FacilityMetadata(
        short_name="Boundary",
        timezone="America/Los_Angeles",
        timezone_label="Pacific",
    ),
    "aeronautical_incident_center": _FacilityMetadata(
        short_name="Aeronautical",
        timezone="America/New_York",
        timezone_label="Eastern",
    ),
    "aerial_phenomena_archive": _FacilityMetadata(
        short_name="Archive",
        timezone="America/Chicago",
        timezone_label="Central",
    ),
    "holography_laboratory": _FacilityMetadata(
        short_name="Holography",
        timezone="America/Denver",
        timezone_label="Mountain",
    ),
    "subsurface_resonance_station": _FacilityMetadata(
        short_name="Subsurface",
        timezone="America/Los_Angeles",
        timezone_label="Pacific",
    ),
    "quantum_state_institute": _FacilityMetadata(
        short_name="Quantum",
        timezone="America/New_York",
        timezone_label="Eastern",
    ),
}


@dataclass(frozen=True, slots=True)
class _PublicTestIdentity:
    assignment_id: str
    working_name: str
    station: str
    palette_token: str


_PUBLIC_TEST_IDENTITIES = {
    "test:investigator-a": _PublicTestIdentity(
        assignment_id="test-assignment-a",
        working_name="Primary Investigator",
        station="Primary Test Console",
        palette_token="cyan-03",
    ),
    "test:reviewer-b": _PublicTestIdentity(
        assignment_id="test-assignment-b",
        working_name="Unclaimed Review Seat",
        station="Independent Review Console",
        palette_token="rust-02",
    ),
}


class V2ActivityProjectionError(ValueError):
    """Raised when authoritative v2 state cannot be safely projected."""


class V2ActivityPublishError(RuntimeError):
    """Raised when the Activity projection could not be refreshed.

    A caller may report the Activity as stale after this error. The v2 event
    stream remains authoritative and must not be rolled back.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status = status


@dataclass(frozen=True, slots=True)
class V2ActivityHttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] | None = None


class V2ActivityHttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> V2ActivityHttpResponse: ...


@dataclass(frozen=True, slots=True)
class V2ActivityPublishResult:
    published: bool
    revision: int
    state_head_hash: str
    snapshot: dict[str, object]

    @property
    def skipped(self) -> bool:
        return not self.published


class _UrllibTransport:
    _USER_AGENT = (
        "HyphaActivityPublisher/0.3 "
        "(+https://example.invalid/uniflora)"
    )

    class _RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    def __init__(self) -> None:
        self._opener = build_opener(self._RejectRedirects)

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> V2ActivityHttpResponse:
        request_headers = {"User-Agent": self._USER_AGENT}
        request_headers.update(headers)
        request = Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=15) as response:  # noqa: S310
                response_body = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(response_body) > _MAX_RESPONSE_BYTES:
                    raise V2ActivityPublishError(
                        "Activity response exceeded the one-megabyte safety limit.",
                        operation=method.casefold(),
                        status=response.status,
                    )
                return V2ActivityHttpResponse(
                    status=response.status,
                    body=response_body,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            return V2ActivityHttpResponse(
                status=error.code,
                body=error.read(_MAX_RESPONSE_BYTES),
                headers=dict(error.headers.items()) if error.headers else None,
            )


def _require_canonical_pack(pack: V2InvestigationPack) -> None:
    if pack.pack.id not in {"missing_interior", "missing_interior_static_roles"}:
        raise V2ActivityProjectionError(
            "the Activity projection only accepts a Missing Interior campaign pack"
        )

    actual_positions = tuple(
        (
            position.id,
            position.ordinal,
            position.title,
            position.focus_location_id,
        )
        for position in pack.positions
    )
    if actual_positions != _POSITION_CONTRACT:
        raise V2ActivityProjectionError(
            "the canonical position contract does not match Activity schema 2.4"
        )

    actual_locations = {location.id for location in pack.locations}
    if actual_locations != set(_FACILITY_METADATA):
        raise V2ActivityProjectionError(
            "the canonical facility contract does not match Activity schema 2.4"
        )


def _normalized_updated_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if value.tzinfo is None or value.utcoffset() is None:
        raise V2ActivityProjectionError("updated_at must include a timezone")
    return value.astimezone(UTC).replace(microsecond=0)


def _iso_zulu(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _copy_publication(
    publication: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if publication is None:
        return None
    if set(publication) != _PUBLICATION_KEYS:
        raise V2ActivityProjectionError(
            "latestPublication must contain exactly the public publication keys"
        )

    required_strings = (
        "publicationId",
        "artifactId",
        "title",
        "institution",
        "finding",
        "limitation",
    )
    if any(
        not isinstance(publication[key], str) or not publication[key]
        for key in required_strings
    ):
        raise V2ActivityProjectionError(
            "latestPublication identifiers and public text must be non-empty strings"
        )
    if publication["status"] not in {"preview", "verified", "published"}:
        raise V2ActivityProjectionError("latestPublication has an invalid status")
    manifest_url = publication["manifestUrl"]
    if manifest_url is not None and (
        not isinstance(manifest_url, str) or not manifest_url
    ):
        raise V2ActivityProjectionError(
            "latestPublication manifestUrl must be null or a non-empty string"
        )

    asset_value = publication["primaryAsset"]
    asset: dict[str, object] | None
    if asset_value is None:
        asset = None
    else:
        if not isinstance(asset_value, Mapping):
            raise V2ActivityProjectionError(
                "latestPublication primaryAsset must be an object or null"
            )
        if set(asset_value) != _PUBLICATION_ASSET_KEYS:
            raise V2ActivityProjectionError(
                "latestPublication primaryAsset must contain exactly the public asset keys"
            )
        string_keys = ("filename", "contentType", "sha256", "url")
        if any(
            not isinstance(asset_value[key], str) or not asset_value[key]
            for key in string_keys
        ):
            raise V2ActivityProjectionError(
                "latestPublication primaryAsset strings must be non-empty"
            )
        byte_length = asset_value["byteLength"]
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
        ):
            raise V2ActivityProjectionError(
                "latestPublication primaryAsset byteLength must be nonnegative"
            )
        asset = {key: asset_value[key] for key in _PUBLICATION_ASSET_KEYS}

    copied = {key: publication[key] for key in _PUBLICATION_KEYS}
    copied["primaryAsset"] = asset
    return copied


def _assignment_status(
    *,
    player_id: str,
    active_role_id: str | None,
    current_position_complete: bool,
    session: V2SessionView,
) -> str:
    if current_position_complete:
        return "complete"
    if any(
        assessment.author_player_id == player_id and assessment.status == "draft"
        for assessment in session.state.assessments
    ):
        return "awaiting-review"
    if active_role_id is not None:
        return "examining"
    return "available"


def _humanize_identifier(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _normalize_basis_points(weights: Mapping[str, int]) -> list[dict[str, object]]:
    if not weights:
        return []
    cleaned = {key: max(0, int(value)) for key, value in weights.items()}
    total = sum(cleaned.values())
    if total <= 0:
        cleaned = {key: 1 for key in cleaned}
        total = len(cleaned)

    floors: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    allocated = 0
    for model_id, weight in sorted(cleaned.items()):
        quotient, remainder = divmod(weight * 10_000, total)
        floors[model_id] = quotient
        remainders.append((remainder, model_id))
        allocated += quotient
    for _, model_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[
        : 10_000 - allocated
    ]:
        floors[model_id] += 1

    return [
        {
            "modelId": model_id,
            "label": _humanize_identifier(model_id),
            "basisPoints": basis_points,
            "percent": basis_points / 100,
        }
        for model_id, basis_points in sorted(
            floors.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def _case_phase(pack: V2InvestigationPack, session: V2SessionView) -> str:
    state = session.state
    position = next(item for item in pack.positions if item.id == state.current_position_id)
    if position.id in state.completed_position_ids:
        return "complete"
    if state.assessments:
        return "review"
    if position.completion.completion_routes and any(
        completion_route_progress(route, state)[0]
        for route in position.completion.completion_routes
    ):
        return "reconcile"
    if state.completed_action_ids or state.stochastic_observations:
        return "perturb"
    return "establish"


def _public_assignments(
    pack: V2InvestigationPack,
    session: V2SessionView,
    *,
    current_position_complete: bool,
) -> list[dict[str, object]]:
    state = session.state
    role_by_id = {role.id: role for role in pack.roles}
    public_players = [
        player for player in state.players
        if player.player_id.startswith(("discord:", "web:"))
    ]
    using_fallback = not public_players
    if using_fallback:
        public_players = [
            player for player in state.players if player.player_id in _PUBLIC_TEST_IDENTITIES
        ]

    palette_tokens = (
        "cyan-03",
        "rust-02",
        "moss-04",
        "amber-03",
        "violet-02",
        "slate-03",
    )
    assignments: list[dict[str, object]] = []
    for index, player in enumerate(public_players):
        role = (
            role_by_id.get(player.active_role_id)
            if player.active_role_id is not None
            else None
        )
        canonical_title = role.name if role is not None else "Unassigned Investigator"
        custom_title = getattr(player, "active_role_display_name", None)
        custom_description = getattr(player, "active_role_description", None)
        role_title = custom_title or canonical_title
        fallback_identity = _PUBLIC_TEST_IDENTITIES.get(player.player_id)
        working_name = (
            fallback_identity.working_name
            if using_fallback and fallback_identity is not None
            else role_title
        )
        station = (
            custom_description
            or (
                fallback_identity.station
                if using_fallback and fallback_identity is not None
                else (f"{role_title} Console" if role is not None else "Unassigned Console")
            )
        )
        assignments.append(
            {
                "assignmentId": f"public-assignment-{index + 1}",
                "workingName": working_name,
                "roleTitle": role_title,
                "locationId": player.current_location_id,
                "station": station,
                "status": _assignment_status(
                    player_id=player.player_id,
                    active_role_id=player.active_role_id,
                    current_position_complete=current_position_complete,
                    session=session,
                ),
                "paletteToken": palette_tokens[index % len(palette_tokens)],
            }
        )
    return assignments


def _public_evidence(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    state = session.state
    evidence_by_id = {item.id: item for item in pack.evidence_sources}
    instrument_by_id = {item.id: item for item in pack.instruments}
    values: list[dict[str, object]] = []
    for evidence_id in sorted(relevant_evidence_ids(pack, state)):
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        if evidence_id in state.examined_evidence_ids:
            status = "examined"
        elif evidence_id in state.available_evidence_ids:
            status = "available"
        else:
            status = "locked"
        instrument = (
            instrument_by_id.get(evidence.instrument_id)
            if evidence.instrument_id is not None
            else None
        )
        values.append(
            {
                "id": evidence.id,
                "name": evidence.name,
                "status": status,
                "sourceClass": evidence.source_class,
                "originLocationId": evidence.origin_location_id,
                "instrumentName": instrument.name if instrument is not None else None,
                "recordType": evidence.raw_or_derived,
            }
        )
    return values


def _action_status(
    pack: V2InvestigationPack,
    action: object,
    session: V2SessionView,
) -> tuple[str, list[str]]:
    state = session.state
    action_id = str(action.id)
    if action_id in state.completed_action_ids:
        return "completed", []
    location_id = str(action.location_id)
    if location_id not in state.available_location_ids:
        return "locked", [f"location:{location_id}"]

    blockers = list(action_context_blockers(pack, action, state))
    if blockers:
        return "developing", blockers
    return "available", []


def _public_actions(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for action in relevant_actions(pack, session.state):
        status, blockers = _action_status(pack, action, session)
        strategic = action_profile(action) if pack.strategic is not None else None
        _, board = preview_strategic_state(pack, session.state)
        strategic_blockers = list(blockers)
        if strategic is not None and board is not None and status != "completed":
            if board.forced_review:
                strategic_blockers.append("position:forced_review")
            if strategic.capacity_cost > board.capacity_remaining:
                strategic_blockers.append(
                    f"capacity:{strategic.capacity_cost}/{board.capacity_remaining}"
                )
            if strategic.coordination_cost > board.coordination:
                strategic_blockers.append(
                    f"coordination:{strategic.coordination_cost}/{board.coordination}"
                )
        if status == "available" and strategic_blockers:
            status = "developing"
        command = None
        if status == "available":
            command = (
                f"propose-action {action.id}"
                if strategic is not None and strategic.supporter_count > 0
                else f"perform-action {action.id}"
            )
        values.append(
            {
                "id": action.id,
                "title": action.title,
                "description": action.description,
                "status": status,
                "command": command,
                "locationId": action.location_id,
                "requiredRoleIds": list(action.prerequisites.required_role_ids),
                "requiredEvidenceIds": list(
                    action.prerequisites.required_examined_evidence_ids
                ),
                "candidateEvidenceIds": list(
                    action.prerequisites.candidate_examined_evidence_ids
                ),
                "minimumExaminedEvidenceCount": (
                    action.prerequisites.minimum_examined_evidence_count
                ),
                "requiredActionIds": list(
                    action.prerequisites.required_completed_action_ids
                ),
                "candidateActionIds": list(
                    action.prerequisites.candidate_completed_action_ids
                ),
                "minimumCompletedActionCount": (
                    action.prerequisites.minimum_completed_action_count
                ),
                "requiredStochasticProcessIds": list(
                    action.prerequisites.required_stochastic_process_ids
                ),
                "minimumObservationCount": (
                    action.prerequisites.minimum_stochastic_observation_count
                ),
                "blockers": strategic_blockers,
                "stochasticProcessId": action.stochastic_process_id,
                "stochasticChannelId": action.stochastic_channel_id,
                "variableOutcome": action.stochastic_process_id is not None,
                "strategicClass": (strategic.strategic_class if strategic is not None else None),
                "capacityCost": (strategic.capacity_cost if strategic is not None else 0),
                "coordinationCost": (strategic.coordination_cost if strategic is not None else 0),
                "supporterCount": (strategic.supporter_count if strategic is not None else 0),
                "irreversible": (strategic.irreversible if strategic is not None else False),
                "stochasticMode": (strategic.stochastic_mode if strategic is not None else "none"),
            }
        )
    return values


def _public_completion_routes(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    state = session.state
    position = next(item for item in pack.positions if item.id == state.current_position_id)
    values: list[dict[str, object]] = []
    for route in position.completion.completion_routes:
        satisfied, progress = completion_route_progress(route, state)
        candidate_count = len(set(route.candidate_action_ids) & state.completed_action_ids)
        observation_count = sum(
            state.stochastic_observation_count(process_id)
            for process_id in route.required_stochastic_process_ids
        )
        values.append(
            {
                "id": route.id,
                "title": route.title,
                "description": route.description,
                "status": "complete" if satisfied else "available",
                "progress": progress,
                "requiredActionIds": list(route.required_action_ids),
                "candidateActionIds": list(route.candidate_action_ids),
                "minimumCompletedActionCount": route.minimum_completed_action_count,
                "completedCandidateCount": candidate_count,
                "requiredStochasticProcessIds": list(
                    route.required_stochastic_process_ids
                ),
                "minimumObservationCount": route.minimum_stochastic_observation_count,
                "observationCount": observation_count,
            }
        )
    return values


def _public_stochastic_processes(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    state = session.state
    actions = relevant_actions(pack, state)
    position = next(item for item in pack.positions if item.id == state.current_position_id)
    relevant_process_ids = {
        action.stochastic_process_id
        for action in actions
        if action.stochastic_process_id is not None
    }
    relevant_process_ids.update(
        process_id
        for route in position.completion.completion_routes
        for process_id in route.required_stochastic_process_ids
    )

    values: list[dict[str, object]] = []
    for process in pack.stochastic_processes:
        if process.id not in relevant_process_ids:
            continue
        process_state = state.get_stochastic_process(process.id)
        support = state.get_stochastic_support(process.id)
        if support is None:
            model_support = _normalize_basis_points(
                {item.model_id: item.weight for item in process.initial_model_weights}
            )
        else:
            model_support = [
                {
                    "modelId": item.model_id,
                    "label": _humanize_identifier(item.model_id),
                    "basisPoints": item.basis_points,
                    "percent": item.basis_points / 100,
                }
                for item in sorted(
                    support.models,
                    key=lambda candidate: (-candidate.basis_points, candidate.model_id),
                )
            ]
        observed_state: str | None = None
        if process.reveal_latent_state:
            state_id = (
                process_state.state_id
                if process_state is not None
                else process.initial_state_id
            )
            definition = next(item for item in process.states if item.id == state_id)
            observed_state = definition.public_label or _humanize_identifier(state_id)
        values.append(
            {
                "id": process.id,
                "title": process.title,
                "description": process.description,
                "locationId": process.location_id,
                "algorithm": process.algorithm,
                "algorithmVersion": process.algorithm_version,
                "observationCount": (
                    process_state.observation_count if process_state is not None else 0
                ),
                "lastSequence": (
                    process_state.last_sequence if process_state is not None else None
                ),
                "observedState": observed_state,
                "modelSupport": model_support,
            }
        )
    return values


def _public_recent_observations(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    relevant_process_ids = {
        item["id"] for item in _public_stochastic_processes(pack, session)
    }
    values: list[dict[str, object]] = []
    for observation in session.state.stochastic_observations:
        if observation.process_id not in relevant_process_ids:
            continue
        values.append(
            {
                "processId": observation.process_id,
                "actionId": observation.action_id,
                "channelId": observation.channel_id,
                # Internal outcome IDs may encode latent-state authoring labels.
                # Publish a stable observed-result identifier without exposing them.
                "outcomeId": f"{observation.action_id}-{observation.sequence}",
                "summary": observation.public_summary,
                "sequence": observation.sequence,
                "observedState": observation.observed_state_label,
                "measurements": [
                    {
                        "key": item.key,
                        "value": item.value,
                        "unit": item.unit,
                        "uncertainty": item.uncertainty,
                    }
                    for item in observation.measurements
                ],
            }
        )
    return values[-12:]


def _public_campaign_tracks(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> list[dict[str, object]]:
    tracks, _ = preview_strategic_state(pack, session.state)
    return [
        {
            "id": item.track_id,
            "label": _humanize_identifier(item.track_id),
            "value": item.value,
            "minimum": item.minimum,
            "maximum": item.maximum,
        }
        for item in tracks
    ]


def _public_strategic_board(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> dict[str, object] | None:
    _, board = preview_strategic_state(pack, session.state)
    if board is None:
        return None
    return {
        "positionId": board.position_id,
        "roundIndex": board.round_index,
        "maxRounds": board.max_rounds,
        "capacityRemaining": board.capacity_remaining,
        "capacityPerRound": board.capacity_per_round,
        "coordination": board.coordination,
        "coordinationMaximum": board.coordination_maximum,
        "escalation": board.escalation,
        "escalationMaximum": board.escalation_maximum,
        "localResource": {
            "id": board.local_resource.resource_id,
            "title": board.local_resource.title,
            "value": board.local_resource.value,
            "minimum": board.local_resource.minimum,
            "maximum": board.local_resource.maximum,
        },
        "conditions": [
            {
                "id": item.condition_id,
                "label": _humanize_identifier(item.condition_id),
                "duration": item.duration,
                "createdRound": item.created_round,
                "expiresAfterRound": item.expires_after_round,
            }
            for item in board.conditions
        ],
        "proposals": [
            {
                "proposalId": item.proposal_id,
                "actionId": item.action_id,
                "roundIndex": item.round_index,
                "requiredSupporterCount": item.required_supporter_count,
                "currentSupporterCount": len(item.supporter_player_ids),
                "status": item.status,
                "command": f"support-action {item.proposal_id}",
            }
            for item in board.proposals
        ],
        "forcedReview": board.forced_review,
    }


def _public_strategic_outcomes(session: V2SessionView) -> list[dict[str, object]]:
    return [
        {
            "positionId": item.position_id,
            "grade": item.grade,
            "roundIndex": item.round_index,
            "caseIntegrity": item.case_integrity,
            "institutionalTrust": item.institutional_trust,
            "escalation": item.escalation,
            "assetIds": list(item.asset_ids),
            "liabilityIds": list(item.liability_ids),
        }
        for item in session.state.strategic_position_outcomes
    ]


def _public_campaign_modifiers(session: V2SessionView) -> list[dict[str, str]]:
    return [
        {"id": item, "label": _humanize_identifier(item)}
        for item in sorted(session.state.campaign_modifier_ids)
    ]


def _adaptive_presentation(
    pack: V2InvestigationPack,
    session: V2SessionView,
) -> dict[str, object] | None:
    state = session.state
    current_position = next(
        item for item in pack.positions if item.id == state.current_position_id
    )
    ending_selection = state.get_adaptation_selection("ending")
    current_selection = state.get_adaptation_selection(current_position.id)
    if current_position.id in state.completed_position_ids and ending_selection is not None:
        if pack.endings is None:
            raise V2ActivityProjectionError("resolved ending is absent from the content pack")
        ending = next(
            (
                candidate
                for candidate in (
                    pack.endings.corrective,
                    pack.endings.baseline,
                    pack.endings.advanced,
                )
                if candidate.presentation_id == ending_selection.presentation_id
            ),
            None,
        )
        if ending is None:
            raise V2ActivityProjectionError("resolved ending presentation is unknown")
        return {
            "presentationId": ending.presentation_id,
            "targetId": "ending",
            "kind": "ending",
            "prose": ending.prose,
            "guidance": [],
            "requiredActionId": None,
            "optionalActionIds": [],
        }
    if current_selection is not None:
        if current_position.adaptation is None:
            raise V2ActivityProjectionError("resolved opening is absent from the content pack")
        variant = next(
            (
                candidate
                for candidate in (
                    current_position.adaptation.corrective,
                    current_position.adaptation.baseline,
                    current_position.adaptation.advanced,
                )
                if candidate.presentation_id == current_selection.presentation_id
            ),
            None,
        )
        if variant is None:
            raise V2ActivityProjectionError("resolved opening presentation is unknown")
        return {
            "presentationId": variant.presentation_id,
            "targetId": current_position.id,
            "kind": "opening",
            "prose": variant.prologue,
            "guidance": list(variant.guidance),
            "requiredActionId": variant.required_action_id,
            "optionalActionIds": list(variant.optional_action_ids),
        }
    if current_position.fixed_opening is None:
        return None
    return {
        "presentationId": current_position.fixed_opening.presentation_id,
        "targetId": current_position.id,
        "kind": "opening",
        "prose": current_position.fixed_opening.prologue,
        "guidance": list(current_position.fixed_opening.guidance),
        "requiredActionId": current_position.fixed_opening.required_action_id,
        "optionalActionIds": list(current_position.fixed_opening.optional_action_ids),
    }


def build_v2_activity_snapshot(
    pack: V2InvestigationPack,
    session: V2SessionView,
    *,
    revision: int,
    previous_state_head_hash: str | None,
    updated_at: datetime | None = None,
    latest_publication: Mapping[str, object] | None = None,
    environment: str = "test",
) -> dict[str, object]:
    """Project authoritative state into the closed public schema-2.4 shape."""

    _require_canonical_pack(pack)
    state = session.state
    if state.pack_id != pack.pack.id:
        raise V2ActivityProjectionError("session and projection pack IDs do not match")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise V2ActivityProjectionError("Activity revision must be a positive integer")
    if previous_state_head_hash is not None and not previous_state_head_hash.strip():
        raise V2ActivityProjectionError("previous_state_head_hash must be null or non-empty")
    if environment not in {"test", "live"}:
        raise V2ActivityProjectionError("Activity environment must be test or live")

    position_by_id = {position.id: position for position in pack.positions}
    current_position = position_by_id.get(state.current_position_id)
    if current_position is None:
        raise V2ActivityProjectionError(
            "the session current position is absent from the canonical pack"
        )

    timestamp = _normalized_updated_at(updated_at)
    facility = _FACILITY_METADATA[current_position.focus_location_id]
    facility_timestamp = timestamp.astimezone(ZoneInfo(facility.timezone))
    current_position_complete = current_position.id in state.completed_position_ids
    assignments = _public_assignments(
        pack,
        session,
        current_position_complete=current_position_complete,
    )

    active_statuses = {"examining", "awaiting-review"}
    active_assignments_by_location = {
        location.id: sum(
            assignment["locationId"] == location.id
            and assignment["status"] in active_statuses
            for assignment in assignments
        )
        for location in pack.locations
    }
    locations = [
        {
            "id": location.id,
            "name": location.name,
            "shortName": _FACILITY_METADATA[location.id].short_name,
            "status": (
                "focus"
                if location.id == current_position.focus_location_id
                else "available"
                if location.id in state.available_location_ids
                else "locked"
            ),
            "timezone": _FACILITY_METADATA[location.id].timezone,
            "activeAssignments": active_assignments_by_location[location.id],
            "mapCoordinates": (
                {
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "label": location.map_label,
                    "precisionKm": location.public_coordinate_precision_km,
                    "basis": "WGS84 facility site",
                }
                if location.latitude is not None
                else None
            ),
        }
        for location in pack.locations
    ]

    positions: list[dict[str, object]] = []
    for position in pack.positions:
        if position.id in state.completed_position_ids:
            progression = "completed"
            console_mode = "reference"
        elif position.id == state.current_position_id:
            progression = "available"
            console_mode = "workspace"
        else:
            progression = "locked"
            console_mode = "locked"
        positions.append(
            {
                "id": position.id,
                "ordinal": position.ordinal,
                "title": position.title,
                "locationId": position.focus_location_id,
                "progression": progression,
                "consoleMode": console_mode,
            }
        )

    unresolved_contradictions = len(
        set(current_position.completion.required_preserved_contradiction_ids)
        - state.preserved_contradiction_ids
    )
    completed_artifacts = sum(
        assessment.status == "confirmed" for assessment in state.assessments
    )
    awaiting_verification = sum(
        assessment.status == "draft" for assessment in state.assessments
    )
    public_player_id = next(
        (
            player.player_id
            for player in state.players
            if player.player_id.startswith("discord:")
        ),
        None,
    )

    snapshot: dict[str, object] = {
        "schemaVersion": _SCHEMA_VERSION,
        "source": _SOURCE,
        "environment": environment,
        "revision": revision,
        "sequence": session.sequence,
        "stateHeadHash": session.last_event_hash,
        "previousStateHeadHash": previous_state_head_hash,
        "positionId": current_position.id,
        "positionTitle": current_position.title,
        "focusLocationId": current_position.focus_location_id,
        "casePhase": _case_phase(pack, session),
        "updatedAt": _iso_zulu(timestamp),
        "zuluTime": timestamp.strftime("%H:%MZ"),
        "facilityTime": facility_timestamp.strftime("%H:%M"),
        "facilityTimezone": facility.timezone_label,
        "metrics": {
            "activeAssignments": sum(
                assignment["status"] in active_statuses for assignment in assignments
            ),
            "completedArtifacts": completed_artifacts,
            "unresolvedContradictions": unresolved_contradictions,
            "awaitingVerification": awaiting_verification,
        },
        "locations": locations,
        "assignments": assignments,
        "latestPublication": _copy_publication(latest_publication),
        "nextRequirement": next_requirement(pack, state, public_player_id),
        "positions": positions,
        "adaptivePresentation": _adaptive_presentation(pack, session),
        "contentVersion": pack.pack.content_version,
        "evidence": _public_evidence(pack, session),
        "actions": _public_actions(pack, session),
        "completionRoutes": _public_completion_routes(pack, session),
        "stochasticProcesses": _public_stochastic_processes(pack, session),
        "recentObservations": _public_recent_observations(pack, session),
        "campaignTracks": _public_campaign_tracks(pack, session),
        "strategicBoard": _public_strategic_board(pack, session),
        "strategicOutcomes": _public_strategic_outcomes(session),
        "campaignModifiers": _public_campaign_modifiers(session),
    }

    if set(snapshot) != _ROOT_KEYS:
        raise AssertionError("internal Activity projection root keys drifted")
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    leaked_ids = [
        player.player_id
        for player in state.players
        if player.player_id in serialized
    ]
    if leaked_ids:
        raise V2ActivityProjectionError(
            "the public Activity projection leaked authoritative player identifiers"
        )
    return snapshot


def project_v2_activity_snapshot(
    pack: V2InvestigationPack,
    session: V2SessionView,
    *,
    revision: int,
    previous_state_head_hash: str | None,
    updated_at: datetime | None = None,
    latest_publication: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compatibility spelling for callers that describe this as projection."""

    return build_v2_activity_snapshot(
        pack,
        session,
        revision=revision,
        previous_state_head_hash=previous_state_head_hash,
        updated_at=updated_at,
        latest_publication=latest_publication,
    )


def _decode_json_object(
    response: V2ActivityHttpResponse,
    *,
    operation: str,
) -> dict[str, object]:
    if not 200 <= response.status < 300:
        detail = response.body[:400].decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise V2ActivityPublishError(
            f"Activity {operation} returned HTTP {response.status}{suffix}",
            operation=operation,
            status=response.status,
        )
    try:
        value = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V2ActivityPublishError(
            f"Activity {operation} returned invalid JSON.",
            operation=operation,
            status=response.status,
        ) from error
    if not isinstance(value, dict):
        raise V2ActivityPublishError(
            f"Activity {operation} response must be a JSON object.",
            operation=operation,
            status=response.status,
        )
    return value


class V2ActivityPublisher:
    """Serialize and HMAC-publish environment-scoped v2 public projections."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        environment: str = "test",
        transport: V2ActivityHttpTransport | None = None,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Activity base URL must be an HTTP(S) origin without a path")
        if parsed.scheme == "http" and (parsed.hostname or "").casefold() not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("Activity base URL must use HTTPS outside loopback development")
        if not secret:
            raise ValueError("Activity HMAC secret must not be empty")
        if environment not in {"test", "live"}:
            raise ValueError("Activity environment must be test or live")

        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._secret = secret.encode("utf-8")
        self._environment = environment
        self._transport = transport or _UrllibTransport()
        self._clock = clock
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._lock = asyncio.Lock()

    async def publish(
        self,
        pack: V2InvestigationPack,
        session: V2SessionView,
        *,
        updated_at: datetime | None = None,
        latest_publication: Mapping[str, object] | None = None,
    ) -> V2ActivityPublishResult:
        """Publish after a v2 commit; failure never mutates or rewinds v2 state."""

        async with self._lock:
            try:
                return await asyncio.to_thread(
                    self._publish_sync,
                    pack,
                    session,
                    updated_at,
                    latest_publication,
                )
            except V2ActivityPublishError:
                raise
            except Exception as error:
                raise V2ActivityPublishError(
                    f"Activity projection publication failed: {error}",
                    operation="publish",
                ) from error

    def _publish_sync(
        self,
        pack: V2InvestigationPack,
        session: V2SessionView,
        updated_at: datetime | None,
        latest_publication: Mapping[str, object] | None,
    ) -> V2ActivityPublishResult:
        current_response = self._transport.request(
            method="GET",
            url=self._origin + f"/api/public-state?environment={self._environment}",
            headers={"Accept": "application/json"},
            body=None,
        )
        if current_response.status == 404 and self._environment == "live":
            missing = json.loads(current_response.body)
            if not isinstance(missing, dict) or missing.get("error") != "state_unavailable":
                raise V2ActivityPublishError(
                    "Activity live state read returned an unexpected 404.",
                    operation="state read", status=404,
                )
            current = {"source": "mock"}
        else:
            current = _decode_json_object(current_response, operation="state read")

        source = current.get("source")
        if source == "mock":
            current_revision = 0
            previous_head = None
            carried_publication = None
        elif source == "hypha":
            if current.get("environment") != self._environment:
                raise V2ActivityPublishError(
                    "Activity state read returned the wrong environment.",
                    operation="state read",
                    status=current_response.status,
                )
            revision_value = current.get("revision")
            head_value = current.get("stateHeadHash")
            if (
                isinstance(revision_value, bool)
                or not isinstance(revision_value, int)
                or revision_value < 1
                or not isinstance(head_value, str)
                or not head_value
            ):
                raise V2ActivityPublishError(
                    "Activity state read returned an invalid revision chain.",
                    operation="state read",
                    status=current_response.status,
                )
            if (
                head_value == session.last_event_hash
                and current.get("schemaVersion") == _SCHEMA_VERSION
                and current.get("contentVersion") == pack.pack.content_version
            ):
                return V2ActivityPublishResult(
                    published=False,
                    revision=revision_value,
                    state_head_hash=head_value,
                    snapshot=current,
                )
            current_revision = revision_value
            previous_head = head_value
            current_publication = current.get("latestPublication")
            if current_publication is not None and not isinstance(current_publication, Mapping):
                raise V2ActivityPublishError(
                    "Activity state read returned an invalid latestPublication.",
                    operation="state read",
                    status=current_response.status,
                )
            carried_publication = current_publication
        else:
            raise V2ActivityPublishError(
                "Activity state read returned an unknown projection source.",
                operation="state read",
                status=current_response.status,
            )

        publication = latest_publication if latest_publication is not None else carried_publication
        try:
            snapshot = build_v2_activity_snapshot(
                pack,
                session,
                revision=current_revision + 1,
                previous_state_head_hash=previous_head,
                updated_at=updated_at,
                latest_publication=publication,
                environment=self._environment,
            )
        except V2ActivityProjectionError as error:
            raise V2ActivityPublishError(
                f"Activity projection rejected authoritative v2 state: {error}",
                operation="projection",
            ) from error

        body = json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        content_sha256 = hashlib.sha256(body).hexdigest()
        timestamp = int(self._clock())
        nonce = self._nonce_factory()
        if not _NONCE_PATTERN.fullmatch(nonce):
            raise V2ActivityPublishError(
                "Activity nonce factory returned an invalid nonce.",
                operation="sign",
            )
        canonical = "\n".join(
            (
                "POST",
                _HYPHA_STATE_PATH,
                str(timestamp),
                nonce,
                content_sha256,
            )
        )
        signature = hmac.new(
            self._secret,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        response = self._transport.request(
            method="POST",
            url=self._origin + _HYPHA_STATE_PATH,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "TheMissingInterior-HyphaPublisher/1.0",
                "X-Hypha-Timestamp": str(timestamp),
                "X-Hypha-Nonce": nonce,
                "X-Hypha-Content-SHA256": content_sha256,
                "X-Hypha-Signature": f"v1={signature}",
            },
            body=body,
        )
        if response.status == 409:
            try:
                conflict = json.loads(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                conflict = None
            if (
                isinstance(conflict, dict)
                and conflict.get("error") == "state_chain_conflict"
                and isinstance(conflict.get("detail"), str)
                and "public_state_revisions.state_head_hash" in conflict["detail"]
                and "UNIQUE constraint failed" in conflict["detail"]
            ):
                refreshed_response = self._transport.request(
                    method="GET",
                    url=self._origin + f"/api/public-state?environment={self._environment}",
                    headers={"Accept": "application/json"},
                    body=None,
                )
                refreshed = _decode_json_object(
                    refreshed_response, operation="state read"
                )
                if (
                    refreshed.get("stateHeadHash") == session.last_event_hash
                    and refreshed.get("schemaVersion") == _SCHEMA_VERSION
                    and refreshed.get("contentVersion") == pack.pack.content_version
                    and isinstance(refreshed.get("revision"), int)
                ):
                    return V2ActivityPublishResult(
                        published=False,
                        revision=refreshed["revision"],
                        state_head_hash=session.last_event_hash,
                        snapshot=refreshed,
                    )
                # The unique event head confirms a prior write even if the
                # public read is briefly stale after the conflict.
                return V2ActivityPublishResult(
                    published=False,
                    revision=current_revision + 1,
                    state_head_hash=session.last_event_hash,
                    snapshot=snapshot,
                )
        acknowledgement = _decode_json_object(response, operation="state publish")
        if (
            acknowledgement.get("ok") is not True
            or acknowledgement.get("environment") != self._environment
            or acknowledgement.get("revision") != snapshot["revision"]
            or acknowledgement.get("stateHeadHash") != snapshot["stateHeadHash"]
        ):
            raise V2ActivityPublishError(
                "Activity state publish returned a mismatched acknowledgement.",
                operation="state publish",
                status=response.status,
            )

        return V2ActivityPublishResult(
            published=True,
            revision=current_revision + 1,
            state_head_hash=session.last_event_hash,
            snapshot=snapshot,
        )


__all__ = [
    "V2ActivityHttpResponse",
    "V2ActivityHttpTransport",
    "V2ActivityProjectionError",
    "V2ActivityPublishError",
    "V2ActivityPublishResult",
    "V2ActivityPublisher",
    "build_v2_activity_snapshot",
    "project_v2_activity_snapshot",
]
