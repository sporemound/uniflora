#!/usr/bin/env python3
"""Run a complete in-memory v2 campaign through one route per position.

The verifier executes the real parser-neutral command/kernel/event/reducer path,
including roles, travel, evidence examination, stochastic observations,
assessment confirmation, position completion, and final replay verification.
It never opens or changes the live SQLite database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uniflora.content.v2 import load_missing_interior_pack  # noqa: E402
from uniflora.engine.v2 import (  # noqa: E402
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2MovePlayerCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    execute_command,
    initialize_event_stream,
    verify_event_stream,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource  # noqa: E402

RouteMode = Literal["primary", "alternate", "alternating"]


class CampaignVerificationError(RuntimeError):
    pass


class CampaignVerifier:
    def __init__(self, *, seed: str, route_mode: RouteMode) -> None:
        self.pack = load_missing_interior_pack()
        self.actor = "discord:campaign-verifier"
        self.reviewer = "discord:independent-verifier"
        self.stream = initialize_event_stream(
            self.pack,
            (self.actor, self.reviewer),
            stream_id=f"campaign-verification-{route_mode}",
        )
        self.random_source = V2SeededRandomSource(seed)
        self.route_mode = route_mode
        self.actions = {item.id: item for item in self.pack.actions}
        self.evidence = {item.id: item for item in self.pack.evidence_sources}
        self._resolution_stack: list[str] = []
        self.position_reports: list[dict[str, object]] = []

    @property
    def state(self):
        return self.stream.state

    @property
    def player(self):
        player = self.state.get_player(self.actor)
        if player is None:
            raise CampaignVerificationError("verification actor left the event stream")
        return player

    def execute(self, command):
        result = execute_command(
            self.pack,
            self.stream,
            command,
            random_source=self.random_source,
        )
        if not result.accepted:
            raise CampaignVerificationError(
                f"{type(command).__name__} rejected: {result.code}: {result.message}"
            )
        self.stream = result.stream
        return result

    def release_role(self) -> None:
        if self.player.active_role_id is not None:
            self.execute(V2ReleaseRoleCommand(player_id=self.actor))

    def move(self, location_id: str) -> None:
        if self.player.current_location_id == location_id:
            return
        self.release_role()
        self.execute(
            V2MovePlayerCommand(
                player_id=self.actor,
                location_id=location_id,
            )
        )

    def assume_role(self, role_id: str, location_id: str) -> None:
        if (
            self.player.active_role_id == role_id
            and self.player.current_location_id == location_id
        ):
            return
        self.release_role()
        self.move(location_id)
        self.execute(
            V2AssignRoleCommand(
                player_id=self.actor,
                role_id=role_id,
            )
        )

    def _unlocking_actions(self, evidence_id: str):
        current_position = self.state.current_position_id
        values = []
        for action in self.pack.actions:
            if action.position_id != current_position:
                continue
            if evidence_id in action.effects.unlock_evidence_ids:
                values.append(action)
                continue
            process = next(
                (
                    item
                    for item in self.pack.stochastic_processes
                    if item.id == action.stochastic_process_id
                ),
                None,
            )
            if process is None:
                continue
            if any(
                evidence_id in outcome.unlock_evidence_ids
                for stochastic_state in process.states
                for emission in stochastic_state.emissions
                if emission.channel_id == action.stochastic_channel_id
                for outcome in emission.outcomes
            ):
                values.append(action)
        return values

    def ensure_evidence(self, evidence_id: str) -> None:
        if evidence_id in self.state.examined_evidence_ids:
            return
        if evidence_id not in self.state.available_evidence_ids:
            last_error: Exception | None = None
            for action in self._unlocking_actions(evidence_id):
                try:
                    self.ensure_action(action.id)
                except CampaignVerificationError as error:
                    last_error = error
                    continue
                if evidence_id in self.state.available_evidence_ids:
                    break
            if evidence_id not in self.state.available_evidence_ids:
                detail = f": {last_error}" if last_error is not None else ""
                raise CampaignVerificationError(
                    f"evidence {evidence_id!r} remained unavailable{detail}"
                )
        source = self.evidence[evidence_id]
        self.move(source.origin_location_id)
        self.execute(
            V2ExamineEvidenceCommand(
                player_id=self.actor,
                evidence_id=evidence_id,
            )
        )

    def ensure_action(self, action_id: str) -> None:
        if action_id in self.state.completed_action_ids:
            return
        if action_id in self._resolution_stack:
            raise CampaignVerificationError(
                "cyclic capability resolution: "
                + " -> ".join((*self._resolution_stack, action_id))
            )
        action = self.actions[action_id]
        if action.position_id != self.state.current_position_id:
            raise CampaignVerificationError(
                f"cross-position dependency: {action_id!r} belongs to "
                f"{action.position_id!r}, current position is "
                f"{self.state.current_position_id!r}"
            )

        self._resolution_stack.append(action_id)
        try:
            for dependency_id in action.prerequisites.required_completed_action_ids:
                self.ensure_action(dependency_id)

            while (
                len(
                    set(action.prerequisites.candidate_completed_action_ids)
                    & self.state.completed_action_ids
                )
                < action.prerequisites.minimum_completed_action_count
            ):
                candidates = [
                    item
                    for item in action.prerequisites.candidate_completed_action_ids
                    if item not in self.state.completed_action_ids
                ]
                if not candidates:
                    raise CampaignVerificationError(
                        f"capability {action_id!r} exhausted its action choices"
                    )
                self.ensure_action(candidates[0])

            for evidence_id in action.prerequisites.required_examined_evidence_ids:
                self.ensure_evidence(evidence_id)

            while (
                len(
                    set(action.prerequisites.candidate_examined_evidence_ids)
                    & self.state.examined_evidence_ids
                )
                < action.prerequisites.minimum_examined_evidence_count
            ):
                candidates = [
                    item
                    for item in action.prerequisites.candidate_examined_evidence_ids
                    if item not in self.state.examined_evidence_ids
                ]
                last_error: Exception | None = None
                for evidence_id in candidates:
                    try:
                        self.ensure_evidence(evidence_id)
                    except CampaignVerificationError as error:
                        last_error = error
                        continue
                    break
                else:
                    raise CampaignVerificationError(
                        f"capability {action_id!r} exhausted its evidence choices: "
                        f"{last_error}"
                    )

            while (
                sum(
                    self.state.stochastic_observation_count(process_id)
                    for process_id in action.prerequisites.required_stochastic_process_ids
                )
                < action.prerequisites.minimum_stochastic_observation_count
            ):
                candidates = [
                    item
                    for item in self.pack.actions
                    if item.position_id == self.state.current_position_id
                    and item.stochastic_process_id
                    in action.prerequisites.required_stochastic_process_ids
                    and item.id not in self.state.completed_action_ids
                    and item.id != action_id
                ]
                if not candidates:
                    raise CampaignVerificationError(
                        f"capability {action_id!r} cannot satisfy its observation gate"
                    )
                self.ensure_action(candidates[0].id)

            if not action.prerequisites.required_role_ids:
                raise CampaignVerificationError(
                    f"capability {action_id!r} has no canonical role"
                )
            self.assume_role(
                action.prerequisites.required_role_ids[0],
                action.location_id,
            )
            self.execute(
                V2PerformActionCommand(
                    player_id=self.actor,
                    action_id=action_id,
                )
            )
        finally:
            self._resolution_stack.pop()

    def _route_index(self, ordinal: int) -> int:
        if self.route_mode == "primary":
            return 0
        if self.route_mode == "alternate":
            return 1
        return ordinal % 2

    def _ensure_assessment_source_classes(self, position) -> None:
        for evidence_id in position.available_evidence_ids_on_entry:
            classes = {
                self.evidence[item].source_class
                for item in self.state.examined_evidence_ids
                if item in self.evidence
            }
            has_position_evidence = bool(
                set(position.available_evidence_ids_on_entry)
                & self.state.examined_evidence_ids
            )
            if (
                len(classes) >= position.completion.minimum_examined_source_classes
                and has_position_evidence
            ):
                return
            self.ensure_evidence(evidence_id)

    def run(self) -> dict[str, object]:
        self.execute(V2BeginInvestigationCommand(player_id=self.actor))

        for ordinal in range(1, 7):
            position = next(item for item in self.pack.positions if item.ordinal == ordinal)
            if self.state.current_position_id != position.id:
                raise CampaignVerificationError(
                    f"expected position {position.id!r}; got {self.state.current_position_id!r}"
                )
            route = position.completion.completion_routes[
                self._route_index(ordinal)
            ]
            sequence_before = self.state.revision
            observations_before = len(self.state.stochastic_observations)
            actions_before = len(self.state.completed_action_ids)

            for action_id in route.required_action_ids:
                self.ensure_action(action_id)
            while (
                len(set(route.candidate_action_ids) & self.state.completed_action_ids)
                < route.minimum_completed_action_count
            ):
                action_id = next(
                    item
                    for item in route.candidate_action_ids
                    if item not in self.state.completed_action_ids
                )
                self.ensure_action(action_id)
            while (
                sum(
                    self.state.stochastic_observation_count(process_id)
                    for process_id in route.required_stochastic_process_ids
                )
                < route.minimum_stochastic_observation_count
            ):
                action = next(
                    item
                    for item in self.pack.actions
                    if item.position_id == position.id
                    and item.stochastic_process_id
                    in route.required_stochastic_process_ids
                    and item.id not in self.state.completed_action_ids
                )
                self.ensure_action(action.id)

            self._ensure_assessment_source_classes(position)
            assessment_id = f"{position.id}_assessment"
            self.execute(
                V2DraftAssessmentCommand(
                    player_id=self.actor,
                    assessment_id=assessment_id,
                    statement=(
                        f"Position {ordinal} retains competing models, preserves the "
                        "required contradiction, and names the remaining collection gap."
                    ),
                    evidence_ids=tuple(sorted(self.state.examined_evidence_ids)),
                    tested_ordinary_explanation_ids=(
                        position.completion.required_tested_ordinary_explanation_ids
                    ),
                    preserved_contradiction_ids=(
                        position.completion.required_preserved_contradiction_ids
                    ),
                    documented_information_gap_ids=(
                        position.completion.required_documented_information_gap_ids
                    ),
                    confidence="moderate",
                    next_collection=(
                        "Collect the highest-value missing independent observation."
                    ),
                )
            )
            self.execute(
                V2ConfirmAssessmentCommand(
                    player_id=self.reviewer,
                    assessment_id=assessment_id,
                )
            )
            self.execute(
                V2CompletePositionCommand(
                    player_id=self.actor,
                    assessment_id=assessment_id,
                )
            )
            self.position_reports.append(
                {
                    "ordinal": ordinal,
                    "positionId": position.id,
                    "routeId": route.id,
                    "sequenceBefore": sequence_before,
                    "sequenceAfter": self.state.revision,
                    "capabilitiesResolved": (
                        len(self.state.completed_action_ids) - actions_before
                    ),
                    "observationsRecorded": (
                        len(self.state.stochastic_observations) - observations_before
                    ),
                }
            )

        verify_event_stream(self.stream)
        return {
            "ok": True,
            "routeMode": self.route_mode,
            "contentVersion": self.pack.pack.content_version,
            "finalSequence": self.state.revision,
            "completedPositions": sorted(self.state.completed_position_ids),
            "totalCapabilities": len(self.state.completed_action_ids),
            "totalObservations": len(self.state.stochastic_observations),
            "positions": self.position_reports,
        }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route",
        choices=("primary", "alternate", "alternating"),
        default="primary",
    )
    parser.add_argument("--seed", default="full-campaign-seed")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = CampaignVerifier(
            seed=args.seed,
            route_mode=args.route,
        ).run()
    except Exception as error:
        if args.json:
            print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        else:
            print(f"CAMPAIGN VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Campaign verification PASS — {report['routeMode']} routes — "
            f"sequence {report['finalSequence']}"
        )
        for position in report["positions"]:
            print(
                f"  Position {position['ordinal']} {position['positionId']} "
                f"via {position['routeId']}: +{position['capabilitiesResolved']} "
                f"capabilities, +{position['observationsRecorded']} observations"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
