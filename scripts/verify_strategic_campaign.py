#!/usr/bin/env python3
"""Verify a complete strategic campaign through the real event/replay path.

Unlike the legacy stochastic route verifier, this script deliberately executes
one preservation operation and one independently supported major intervention
in every position before completing the selected investigation route.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.verify_stochastic_campaign import (  # noqa: E402
    CampaignVerificationError,
    CampaignVerifier,
)
from uniflora.engine.v2 import (  # noqa: E402
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2MovePlayerCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2ReleaseRoleCommand,
    V2SupportActionCommand,
    verify_event_stream,
)

Policy = Literal[
    "conservative_preservation",
    "aggressive_information",
    "balanced",
    "random_legal",
]

_PREPARATION_BY_POSITION = {
    "boundary_event": "preserve_raw_channel_snapshot",
    "aeronautical_incident": "preserve_raw_sensor_products",
    "archive_convergence": "quarantine_source_dependencies",
    "holographic_reconstruction": "freeze_reconstruction_parameters",
    "subsurface_resonance": "synchronize_station_clocks",
    "quantum_state": "lock_preparation_readout_ledger",
}

_MAJOR_BY_POSITION = {
    "boundary_event": "run_synchronized_reacquisition",
    "aeronautical_incident": "authorize_joint_sensor_retasking",
    "archive_convergence": "open_restricted_accession_window",
    "holographic_reconstruction": "run_phase_lock_intervention",
    "subsurface_resonance": "activate_regional_station_array",
    "quantum_state": "execute_cross_basis_tomography",
}


class StrategicCampaignVerifier(CampaignVerifier):
    def __init__(self, *, seed: str, route_mode: str, policy: Policy) -> None:
        super().__init__(seed=seed, route_mode=route_mode)  # type: ignore[arg-type]
        self.policy = policy
        self.policy_random = random.Random(f"{seed}|{route_mode}|{policy}")
        self.strategic_reports: list[dict[str, object]] = []

    @property
    def reviewer_player(self):
        value = self.state.get_player(self.reviewer)
        if value is None:
            raise CampaignVerificationError("verification reviewer left the event stream")
        return value

    def prepare_reviewer(self, action_id: str) -> None:
        action = self.actions[action_id]
        if not action.prerequisites.required_role_ids:
            raise CampaignVerificationError(
                f"major operation {action_id!r} has no canonical role"
            )
        player = self.reviewer_player
        if player.active_role_id is not None:
            self.execute(V2ReleaseRoleCommand(player_id=self.reviewer))
            player = self.reviewer_player
        if player.current_location_id != action.location_id:
            self.execute(
                V2MovePlayerCommand(
                    player_id=self.reviewer,
                    location_id=action.location_id,
                )
            )
        self.execute(
            V2AssignRoleCommand(
                player_id=self.reviewer,
                role_id=action.prerequisites.required_role_ids[0],
            )
        )

    def execute_policy(self, position_id: str) -> None:
        prep_id = _PREPARATION_BY_POSITION[position_id]
        major_id = _MAJOR_BY_POSITION[position_id]
        do_prep = self.policy in {"conservative_preservation", "balanced"}
        do_major = self.policy in {"aggressive_information", "balanced"}
        if self.policy == "random_legal":
            do_prep = bool(self.policy_random.getrandbits(1))
            do_major = bool(self.policy_random.getrandbits(1))

        # Major operations require one Coordination. A preparation by the first
        # participant creates it without spending a separate coordination event.
        if do_major and not do_prep:
            do_prep = True

        sequence_before = self.state.revision
        observations_before = len(self.state.stochastic_observations)
        if do_prep:
            self.ensure_action(prep_id)
        proposal_id: str | None = None
        if do_major:
            self.prepare_reviewer(major_id)
            proposed = self.execute(
                V2ProposeActionCommand(
                    player_id=self.reviewer,
                    action_id=major_id,
                )
            )
            if proposed.event is None:
                raise CampaignVerificationError("major proposal produced no event")
            proposal_id = proposed.event.proposal.proposal_id
            resolved = self.execute(
                V2SupportActionCommand(
                    player_id=self.actor,
                    proposal_id=proposal_id,
                )
            )
            if resolved.code != "major_action_resolved":
                raise CampaignVerificationError(
                    f"major proposal {proposal_id!r} did not resolve atomically"
                )

        board = self.state.strategic_board
        self.strategic_reports.append(
            {
                "positionId": position_id,
                "policy": self.policy,
                "preparationActionId": prep_id if do_prep else None,
                "majorActionId": major_id if do_major else None,
                "proposalId": proposal_id,
                "sequenceBefore": sequence_before,
                "sequenceAfter": self.state.revision,
                "observationsRecorded": (
                    len(self.state.stochastic_observations) - observations_before
                ),
                "roundAfter": board.round_index if board is not None else None,
                "capacityAfter": board.capacity_remaining if board is not None else None,
            }
        )

    def run(self) -> dict[str, object]:
        self.execute(V2BeginInvestigationCommand(player_id=self.actor))

        for ordinal in range(1, 7):
            position = next(item for item in self.pack.positions if item.ordinal == ordinal)
            if self.state.current_position_id != position.id:
                raise CampaignVerificationError(
                    f"expected position {position.id!r}; got {self.state.current_position_id!r}"
                )
            route = position.completion.completion_routes[self._route_index(ordinal)]
            sequence_before = self.state.revision
            observations_before = len(self.state.stochastic_observations)
            actions_before = len(self.state.completed_action_ids)

            self.execute_policy(position.id)

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
            assessment_id = f"{position.id}_strategic_assessment"
            self.execute(
                V2DraftAssessmentCommand(
                    player_id=self.actor,
                    assessment_id=assessment_id,
                    statement=(
                        f"Position {ordinal} records the strategic commitments, "
                        "retains competing models, preserves the required "
                        "contradiction, and names the remaining collection gap."
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
                    next_collection="Preserve the highest-value independent collection.",
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
            outcome = self.state.strategic_position_outcomes[-1]
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
                    "strategicGrade": outcome.grade,
                    "assets": list(outcome.asset_ids),
                    "liabilities": list(outcome.liability_ids),
                }
            )

        verify_event_stream(self.stream)
        return {
            "ok": True,
            "routeMode": self.route_mode,
            "policy": self.policy,
            "contentVersion": self.pack.pack.content_version,
            "finalSequence": self.state.revision,
            "completedPositions": sorted(self.state.completed_position_ids),
            "totalCapabilities": len(self.state.completed_action_ids),
            "totalObservations": len(self.state.stochastic_observations),
            "campaignTracks": {
                item.track_id: item.value for item in self.state.campaign_tracks
            },
            "campaignModifiers": sorted(self.state.campaign_modifier_ids),
            "positions": self.position_reports,
            "strategicOperations": self.strategic_reports,
        }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route",
        choices=("primary", "alternate", "alternating"),
        default="primary",
    )
    parser.add_argument(
        "--policy",
        choices=(
            "conservative_preservation",
            "aggressive_information",
            "balanced",
            "random_legal",
        ),
        default="balanced",
    )
    parser.add_argument("--seed", default="strategic-campaign-seed")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = StrategicCampaignVerifier(
            seed=args.seed,
            route_mode=args.route,
            policy=args.policy,
        ).run()
    except Exception as error:
        failure = {"ok": False, "error": str(error)}
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        if args.json:
            print(json.dumps(failure, indent=2))
        else:
            print(f"STRATEGIC CAMPAIGN VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Strategic campaign PASS — {report['routeMode']} routes — "
            f"{report['policy']} policy — sequence {report['finalSequence']}"
        )
        for position in report["positions"]:
            print(
                f"  Position {position['ordinal']} {position['positionId']} "
                f"via {position['routeId']}: {position['strategicGrade']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
