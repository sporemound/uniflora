#!/usr/bin/env python3
"""Audit strategic content, reachability, grading, and public invariants."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uniflora.content.v2 import load_missing_interior_pack  # noqa: E402
from uniflora.engine.v2 import (  # noqa: E402
    V2BeginInvestigationCommand,
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.state import V2StrategicTrackState  # noqa: E402
from uniflora.engine.v2.strategic import (  # noqa: E402
    grade_current_position,
    preview_strategic_state,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource  # noqa: E402


def _grade_reachability(pack) -> dict[str, bool]:
    player = "discord:strategic-audit"
    stream = initialize_event_stream(pack, (player,), stream_id="strategic-audit")
    result = execute_command(
        pack,
        stream,
        V2BeginInvestigationCommand(player_id=player),
        random_source=V2SeededRandomSource("strategic-audit"),
    )
    if not result.accepted:
        raise RuntimeError(result.message)
    state = result.stream.state
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        raise RuntimeError("Position 1 did not produce a strategic board preview")

    by_id = {item.track_id: item for item in tracks}

    def with_values(*, integrity: int, trust: int, escalation: int, forced: bool):
        modified_tracks = (
            replace(by_id["case_integrity"], value=integrity),
            replace(by_id["institutional_trust"], value=trust),
        )
        modified = replace(
            state,
            campaign_tracks=modified_tracks,
            strategic_board=replace(
                board,
                escalation=escalation,
                capacity_remaining=(0 if forced else board.capacity_remaining),
                forced_review=forced,
            ),
            serialization_schema=4,
        )
        outcome, _, _ = grade_current_position(pack, modified)
        return outcome.grade if outcome is not None else None

    observed = {
        with_values(integrity=5, trust=5, escalation=0, forced=False),
        with_values(integrity=4, trust=5, escalation=1, forced=False),
        with_values(integrity=5, trust=5, escalation=0, forced=True),
        with_values(integrity=1, trust=5, escalation=0, forced=False),
    }
    return {
        grade: grade in observed
        for grade in ("controlled", "compromised", "incomplete", "critical")
    }


def audit() -> dict[str, object]:
    pack = load_missing_interior_pack()
    if pack.strategic is None:
        raise RuntimeError("canonical pack has no strategic campaign definition")

    actions_by_position: dict[str, list] = {}
    for action in pack.actions:
        if action.position_id is not None:
            actions_by_position.setdefault(action.position_id, []).append(action)
    processes = {item.id: item for item in pack.stochastic_processes}

    position_reports: list[dict[str, object]] = []
    failures: list[str] = []
    for rules in pack.strategic.positions:
        actions = actions_by_position.get(rules.position_id, [])
        major = [
            item
            for item in actions
            if item.strategic is not None and item.strategic.supporter_count > 0
        ]
        preparations = [
            item
            for item in actions
            if item.strategic is not None
            and item.strategic.deterministic_effects.add_conditions
        ]
        transition_modifiers = [
            modifier
            for item in actions
            if item.strategic is not None
            for modifier in item.strategic.transition_modifiers
        ]
        emission_modifiers = [
            modifier
            for item in actions
            if item.strategic is not None
            for modifier in item.strategic.emission_modifiers
        ]
        route_position = next(
            item for item in pack.positions if item.id == rules.position_id
        )
        routes_valid = all(
            route.minimum_completed_action_count <= len(route.candidate_action_ids)
            and not (
                (set(route.required_action_ids) | set(route.candidate_action_ids))
                - {item.id for item in pack.actions}
            )
            for route in route_position.completion.completion_routes
        )
        report = {
            "positionId": rules.position_id,
            "localResourceId": rules.local_resource.id,
            "naturalDriftProcessId": rules.natural_drift_process_id,
            "naturalDriftProcessExists": rules.natural_drift_process_id in processes,
            "majorActions": [item.id for item in major],
            "preparationActions": [item.id for item in preparations],
            "transitionModifierCount": len(transition_modifiers),
            "emissionModifierCount": len(emission_modifiers),
            "routeCount": len(route_position.completion.completion_routes),
            "routesValid": routes_valid,
        }
        if len(major) != 1:
            failures.append(
                f"{rules.position_id}: expected one major action, found {len(major)}"
            )
        if not preparations:
            failures.append(f"{rules.position_id}: no condition-setting preparation")
        if not transition_modifiers:
            failures.append(f"{rules.position_id}: no transition modifier")
        if not emission_modifiers:
            failures.append(f"{rules.position_id}: no emission modifier")
        if rules.natural_drift_process_id not in processes:
            failures.append(f"{rules.position_id}: missing natural-drift process")
        if not routes_valid:
            failures.append(f"{rules.position_id}: invalid completion route")
        position_reports.append(report)

    hidden_state_tags = {
        state.id: sorted(set(state.tags))
        for process in pack.stochastic_processes
        for state in process.states
    }
    outcome_tags = {
        outcome.id: sorted(set(outcome.tags))
        for process in pack.stochastic_processes
        for state in process.states
        for emission in state.emissions
        for outcome in emission.outcomes
    }
    untagged_states = sorted(key for key, value in hidden_state_tags.items() if not value)
    untagged_outcomes = sorted(key for key, value in outcome_tags.items() if not value)
    if untagged_states:
        failures.append(f"untagged hidden states: {', '.join(untagged_states)}")
    if untagged_outcomes:
        failures.append(f"untagged outcomes: {', '.join(untagged_outcomes)}")

    grade_reachability = _grade_reachability(pack)
    if not all(grade_reachability.values()):
        failures.append("not all strategic outcome grades are reachable")

    return {
        "ok": not failures,
        "packId": pack.pack.id,
        "contentVersion": pack.pack.content_version,
        "schemaVersion": pack.schema_version,
        "stateSerializationSchema": 4,
        "activitySchemaVersion": "2.4.0",
        "campaignTracks": [item.id for item in pack.strategic.campaign_tracks],
        "positionCount": len(position_reports),
        "positions": position_reports,
        "majorActionCount": sum(len(item["majorActions"]) for item in position_reports),
        "hiddenStateCount": len(hidden_state_tags),
        "outcomeCount": len(outcome_tags),
        "untaggedStates": untagged_states,
        "untaggedOutcomes": untagged_outcomes,
        "gradeReachability": grade_reachability,
        "ordinaryOutcomesPenalized": False,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = audit()
    except Exception as error:
        report = {"ok": False, "failures": [str(error)]}
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or not report["ok"]:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Strategic audit PASS — {report['positionCount']} positions, "
            f"{report['majorActionCount']} major operations"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
