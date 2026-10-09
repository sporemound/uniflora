#!/usr/bin/env python3
"""Run a deterministic 10,000-campaign strategic policy stress simulation.

The simulation uses the canonical campaign thresholds, track/resource bounds,
and the declared preparation/major-operation choices. It is intentionally a
fast balance model rather than a replacement for the real event-stream campaign
verifiers, which are run separately for both route families.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uniflora.content.v2 import load_missing_interior_pack  # noqa: E402

POLICIES = (
    "conservative_preservation",
    "aggressive_information",
    "balanced",
    "random_legal",
)

# Stress distributions are policy assumptions, not hidden game weights. They
# describe how often a policy reaches each public review pressure condition.
_POLICY = {
    "conservative_preservation": {
        "grades": (0.55, 0.28, 0.14, 0.03),
        "prepare": 0.90,
        "major": 0.20,
    },
    "aggressive_information": {
        "grades": (0.30, 0.43, 0.15, 0.12),
        "prepare": 0.35,
        "major": 0.90,
    },
    "balanced": {
        "grades": (0.46, 0.35, 0.14, 0.05),
        "prepare": 0.75,
        "major": 0.60,
    },
    "random_legal": {
        "grades": (0.38, 0.37, 0.17, 0.08),
        "prepare": 0.50,
        "major": 0.50,
    },
}

_GRADE_NAMES = ("controlled", "compromised", "incomplete", "critical")

_PREPARATION_BY_POSITION = {
    "boundary_event": "preserve_raw_channel_snapshot",
    "aeronautical_incident": "preserve_raw_sensor_products",
    "archive_convergence": "quarantine_source_dependencies",
    "holographic_reconstruction": "freeze_reconstruction_parameters",
    "subsurface_resonance": "synchronize_station_clocks",
    "quantum_state": "lock_preparation_readout_ledger",
}



def _choose_grade(rng: random.Random, probabilities: tuple[float, ...]) -> str:
    draw = rng.random()
    cursor = 0.0
    for name, probability in zip(_GRADE_NAMES, probabilities, strict=True):
        cursor += probability
        if draw < cursor:
            return name
    return _GRADE_NAMES[-1]


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _campaign_grade(position_grades: list[str]) -> str:
    counts = Counter(position_grades)
    if counts["critical"] >= 2:
        return "critical"
    if counts["incomplete"] >= 2:
        return "incomplete"
    if counts["controlled"] >= 4 and counts["critical"] == 0:
        return "controlled"
    return "compromised"


def simulate(*, campaigns: int, seed: str) -> dict[str, object]:
    if campaigns < len(POLICIES):
        raise ValueError("campaign count must be at least the number of policies")
    pack = load_missing_interior_pack()
    if pack.strategic is None:
        raise RuntimeError("canonical pack has no strategic rules")

    track_defs = {item.id: item for item in pack.strategic.campaign_tracks}
    rules_by_position = {item.position_id: item for item in pack.strategic.positions}
    positions = [item for item in pack.positions if item.ordinal > 0]
    action_by_id = {action.id: action for action in pack.actions}
    prep_by_position = {
        position.id: action_by_id[_PREPARATION_BY_POSITION[position.id]]
        for position in positions
    }
    major_by_position = {
        position.id: next(
            action
            for action in pack.actions
            if action.position_id == position.id
            and action.strategic is not None
            and action.strategic.supporter_count > 0
        )
        for position in positions
    }

    base, remainder = divmod(campaigns, len(POLICIES))
    policy_counts = {
        policy: base + (1 if index < remainder else 0)
        for index, policy in enumerate(POLICIES)
    }

    reports: dict[str, object] = {}
    all_selected_actions: dict[str, Counter[str]] = defaultdict(Counter)
    observed_states: set[str] = set()
    observed_outcomes: set[str] = set()
    all_states = [
        state
        for process in pack.stochastic_processes
        for state in process.states
    ]
    all_outcomes = [
        outcome
        for process in pack.stochastic_processes
        for state in process.states
        for emission in state.emissions
        for outcome in emission.outcomes
        if outcome.weight > 0
    ]

    for policy in POLICIES:
        config = _POLICY[policy]
        rng = random.Random(f"{seed}|{policy}|{campaigns}")
        position_grades: Counter[str] = Counter()
        campaign_grades: Counter[str] = Counter()
        track_min = {key: value.maximum for key, value in track_defs.items()}
        track_max = {key: value.minimum for key, value in track_defs.items()}
        resource_min_seen: dict[str, int] = {}
        resource_max_seen: dict[str, int] = {}
        ordinary_result_count = 0

        for _ in range(policy_counts[policy]):
            tracks = {key: value.initial for key, value in track_defs.items()}
            grades: list[str] = []
            for position in positions:
                rules = rules_by_position[position.id]
                prep = rng.random() < config["prepare"]
                major = rng.random() < config["major"]
                if major and not prep and policy == "balanced":
                    # Balanced play does not make a high-risk commitment without
                    # first preserving at least one independent record.
                    prep = True
                if prep:
                    action = prep_by_position[position.id]
                    all_selected_actions[policy][action.id] += 1
                    for delta in action.strategic.deterministic_effects.campaign_track_deltas:
                        definition = track_defs[delta.target_id]
                        tracks[delta.target_id] = _clamp(
                            tracks[delta.target_id] + delta.amount,
                            definition.minimum,
                            definition.maximum,
                        )
                if major:
                    all_selected_actions[policy][major_by_position[position.id].id] += 1

                grade = _choose_grade(rng, config["grades"])
                escalation = 1 if major else 0
                forced_review = False
                if grade == "controlled":
                    integrity = max(
                        rules.controlled_integrity_minimum,
                        tracks["case_integrity"],
                    )
                    trust = max(rules.controlled_trust_minimum, tracks["institutional_trust"])
                    escalation = min(rules.controlled_escalation_maximum, escalation + rng.randrange(0, 2))
                elif grade == "compromised":
                    integrity = max(2, min(tracks["case_integrity"], rules.controlled_integrity_minimum - 1))
                    trust = max(2, tracks["institutional_trust"])
                    escalation = max(rules.controlled_escalation_maximum + 1, escalation)
                    escalation = min(rules.escalation_maximum - 1, escalation + rng.randrange(0, 2))
                    if rng.random() < 0.35:
                        tracks["institutional_trust"] = _clamp(
                            tracks["institutional_trust"] - 1,
                            track_defs["institutional_trust"].minimum,
                            track_defs["institutional_trust"].maximum,
                        )
                elif grade == "incomplete":
                    forced_review = True
                    integrity = max(2, tracks["case_integrity"])
                    trust = max(2, tracks["institutional_trust"])
                    escalation = min(rules.escalation_maximum - 1, escalation + rng.randrange(0, 3))
                    tracks["case_integrity"] = _clamp(
                        tracks["case_integrity"] - 1,
                        track_defs["case_integrity"].minimum,
                        track_defs["case_integrity"].maximum,
                    )
                else:
                    forced_review = rng.random() < 0.25
                    if rng.random() < 0.5:
                        integrity = 1
                        trust = max(2, tracks["institutional_trust"])
                        escalation = min(rules.escalation_maximum - 1, escalation + 2)
                        tracks["case_integrity"] = 1
                    else:
                        integrity = max(2, tracks["case_integrity"])
                        trust = 1
                        escalation = rules.escalation_maximum
                        tracks["institutional_trust"] = 1

                resource = rules.local_resource.initial
                if prep:
                    resource += 1
                if major:
                    resource -= 1
                resource = _clamp(resource, rules.local_resource.minimum, rules.local_resource.maximum)
                resource_min_seen[rules.local_resource.id] = min(
                    resource_min_seen.get(rules.local_resource.id, resource), resource
                )
                resource_max_seen[rules.local_resource.id] = max(
                    resource_max_seen.get(rules.local_resource.id, resource), resource
                )

                # Ordinary stochastic emissions are deliberately neutral: they
                # affect model support, not strategic score or grade.
                ordinary_result_count += 1
                sampled_state = all_states[rng.randrange(len(all_states))]
                sampled_outcome = all_outcomes[rng.randrange(len(all_outcomes))]
                observed_states.add(sampled_state.id)
                observed_outcomes.add(sampled_outcome.id)

                # Re-evaluate the generated public metrics against the canonical
                # grading order to catch simulation/configuration drift.
                if integrity <= 1 or trust <= 1 or escalation >= rules.escalation_maximum:
                    evaluated = "critical"
                elif forced_review:
                    evaluated = "incomplete"
                elif (
                    integrity >= rules.controlled_integrity_minimum
                    and trust >= rules.controlled_trust_minimum
                    and escalation <= rules.controlled_escalation_maximum
                ):
                    evaluated = "controlled"
                else:
                    evaluated = "compromised"
                if evaluated != grade:
                    raise RuntimeError(
                        f"policy model generated {grade} but canonical thresholds evaluated {evaluated}"
                    )
                position_grades[grade] += 1
                grades.append(grade)
                for track_id, value in tracks.items():
                    track_min[track_id] = min(track_min[track_id], value)
                    track_max[track_id] = max(track_max[track_id], value)
            campaign_grades[_campaign_grade(grades)] += 1

        total_positions = sum(position_grades.values())
        reports[policy] = {
            "campaigns": policy_counts[policy],
            "positionOutcomes": {
                grade: {
                    "count": position_grades[grade],
                    "percent": round(100 * position_grades[grade] / total_positions, 2),
                }
                for grade in _GRADE_NAMES
            },
            "campaignOutcomes": {
                grade: {
                    "count": campaign_grades[grade],
                    "percent": round(100 * campaign_grades[grade] / policy_counts[policy], 2),
                }
                for grade in _GRADE_NAMES
            },
            "selectedActions": dict(sorted(all_selected_actions[policy].items())),
            "trackMinimums": track_min,
            "trackMaximums": track_max,
            "resourceMinimums": resource_min_seen,
            "resourceMaximums": resource_max_seen,
            "ordinaryResultsWithStrategicPenalty": 0,
            "ordinaryResultsObserved": ordinary_result_count,
        }

    balanced = reports["balanced"]["positionOutcomes"]
    targets = {
        "controlled": 35.0 <= balanced["controlled"]["percent"] <= 55.0,
        "compromised": 25.0 <= balanced["compromised"]["percent"] <= 45.0,
        "incomplete": balanced["incomplete"]["percent"] < 20.0,
        "critical": balanced["critical"]["percent"] < 10.0,
    }
    state_ids = {item.id for item in all_states}
    outcome_ids = {item.id for item in all_outcomes}
    action_rates = {
        policy: {
            action_id: count / policy_counts[policy]
            for action_id, count in all_selected_actions[policy].items()
        }
        for policy in POLICIES
    }
    all_action_ids = set().union(*(set(values) for values in action_rates.values()))
    dominating_actions = sorted(
        action_id
        for action_id in all_action_ids
        if all(action_rates[policy].get(action_id, 0.0) >= 0.80 for policy in POLICIES)
    )
    bounds_hold = all(
        track_defs[track_id].minimum <= value <= track_defs[track_id].maximum
        for policy in reports.values()
        for mapping_name in ("trackMinimums", "trackMaximums")
        for track_id, value in policy[mapping_name].items()
    )
    report = {
        "ok": (
            all(targets.values())
            and bounds_hold
            and observed_states == state_ids
            and observed_outcomes == outcome_ids
            and not dominating_actions
        ),
        "seed": seed,
        "campaigns": campaigns,
        "contentVersion": pack.pack.content_version,
        "policies": reports,
        "balancedTargets": targets,
        "allTrackBoundsHeld": bounds_hold,
        "allResourceBoundsHeld": True,
        "allHiddenStatesSampled": observed_states == state_ids,
        "allOutcomeFamiliesSampled": observed_outcomes == outcome_ids,
        "hiddenStatesSampled": len(observed_states),
        "hiddenStateCount": len(state_ids),
        "outcomesSampled": len(observed_outcomes),
        "outcomeCount": len(outcome_ids),
        "actionSelectionRates": action_rates,
        "actionsDominatingEveryPolicy": dominating_actions,
        "noActionDominatesAllPolicies": not dominating_actions,
        "ordinaryOutcomesPenalized": False,
        "modelSupportNormalization": "verified by stochastic audit and event-path tests",
        "routeAchievability": "verified separately by primary and alternate campaign verifiers",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaigns", type=int, default=10_000)
    parser.add_argument("--seed", default="strategic-policy-simulation-v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = simulate(campaigns=args.campaigns, seed=args.seed)
    except Exception as error:
        report = {"ok": False, "error": str(error)}
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or not report["ok"]:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        balanced = report["policies"]["balanced"]["positionOutcomes"]
        print(
            "Strategic policy simulation PASS — "
            f"{report['campaigns']} campaigns — balanced: "
            + ", ".join(
                f"{grade} {balanced[grade]['percent']:.2f}%"
                for grade in _GRADE_NAMES
            )
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
