#!/usr/bin/env python3
"""Audit The Missing Interior stochastic processes and route structure.

This tool never touches the live SQLite stream. It runs content-driven seeded
chains in memory, reports outcome/state distributions, and verifies that model
support remains normalized. It is intended for balancing before deployment.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uniflora.content.v2 import load_missing_interior_pack  # noqa: E402
from uniflora.engine.v2.state import V2InvestigationState  # noqa: E402
from uniflora.engine.v2.stochastic import (  # noqa: E402
    V2SeededRandomSource,
    resolve_stochastic_action,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic balancing simulations for the v2 stochastic overhaul."
        )
    )
    parser.add_argument("--chains", type=int, default=24, help="Independent chains/process")
    parser.add_argument("--steps", type=int, default=32, help="Steps in each chain")
    parser.add_argument("--seed", default="missing-interior-audit", help="Base audit seed")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    values = parser.parse_args()
    if values.chains < 1 or values.steps < 1:
        parser.error("--chains and --steps must be positive")
    return values


def _route_report(pack) -> list[dict[str, object]]:
    action_ids = {action.id for action in pack.actions}
    reports: list[dict[str, object]] = []
    for position in pack.positions:
        if position.ordinal == 0:
            continue
        routes = []
        for route in position.completion.completion_routes:
            referenced = set(route.required_action_ids) | set(route.candidate_action_ids)
            missing = sorted(referenced - action_ids)
            routes.append(
                {
                    "id": route.id,
                    "title": route.title,
                    "requiredActions": len(route.required_action_ids),
                    "candidateActions": len(route.candidate_action_ids),
                    "candidateMinimum": route.minimum_completed_action_count,
                    "minimumObservations": route.minimum_stochastic_observation_count,
                    "missingActions": missing,
                    "structurallyValid": (
                        not missing
                        and route.minimum_completed_action_count
                        <= len(route.candidate_action_ids)
                    ),
                }
            )
        reports.append(
            {
                "positionId": position.id,
                "ordinal": position.ordinal,
                "routeCount": len(routes),
                "routes": routes,
            }
        )
    return reports


def _process_report(pack, process, *, chains: int, steps: int, seed: str) -> dict[str, object]:
    actions = [
        action for action in pack.actions if action.stochastic_process_id == process.id
    ]
    if not actions:
        raise RuntimeError(f"process {process.id!r} has no bound capability")

    outcome_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    final_support: dict[str, list[int]] = defaultdict(list)
    observed_measurements: Counter[str] = Counter()

    for chain_index in range(chains):
        state = V2InvestigationState(
            pack_id=pack.pack.id,
            current_position_id=next(
                position.id
                for position in pack.positions
                if position.focus_location_id == process.location_id
                and position.ordinal > 0
            ),
            available_location_ids=frozenset({process.location_id}),
            players=(),
            available_evidence_ids=frozenset(),
        )
        random_source = V2SeededRandomSource(
            f"{seed}|{process.id}|chain:{chain_index}"
        )
        for step_index in range(steps):
            action = actions[step_index % len(actions)]
            state, resolution, _ = resolve_stochastic_action(
                state,
                action,
                process,
                random_source=random_source,
            )
            outcome_counts[resolution.outcome_id] += 1
            state_counts[resolution.next_state_id] += 1
            for measurement in resolution.measurements:
                observed_measurements[measurement.key] += 1
            total = sum(
                item.basis_points for item in resolution.model_support_after.models
            )
            if total != 10_000:
                raise RuntimeError(
                    f"process {process.id!r} produced non-normalized support {total}"
                )

        support = state.get_stochastic_support(process.id)
        if support is None:
            raise RuntimeError(f"process {process.id!r} did not produce model support")
        for item in support.models:
            final_support[item.model_id].append(item.basis_points)

    total_draws = chains * steps
    return {
        "id": process.id,
        "title": process.title,
        "algorithm": process.algorithm,
        "algorithmVersion": process.algorithm_version,
        "chains": chains,
        "stepsPerChain": steps,
        "totalDraws": total_draws,
        "boundCapabilities": [action.id for action in actions],
        "stateOccupancy": {
            key: {
                "count": count,
                "percent": round(count * 100 / total_draws, 2),
            }
            for key, count in sorted(state_counts.items())
        },
        "outcomes": {
            key: {
                "count": count,
                "percent": round(count * 100 / total_draws, 2),
            }
            for key, count in sorted(outcome_counts.items())
        },
        "measurementCoverage": dict(sorted(observed_measurements.items())),
        "meanFinalModelSupportBasisPoints": {
            model_id: round(sum(values) / len(values), 2)
            for model_id, values in sorted(final_support.items())
        },
    }


def main() -> int:
    args = _arguments()
    pack = load_missing_interior_pack()
    report = {
        "packId": pack.pack.id,
        "contentVersion": pack.pack.content_version,
        "seed": args.seed,
        "routeAudit": _route_report(pack),
        "processes": [
            _process_report(
                pack,
                process,
                chains=args.chains,
                steps=args.steps,
                seed=args.seed,
            )
            for process in pack.stochastic_processes
        ],
    }
    report["ok"] = all(
        route["structurallyValid"]
        for position in report["routeAudit"]
        for route in position["routes"]
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"{report['packId']} {report['contentVersion']} — "
            f"{len(report['processes'])} stochastic processes"
        )
        for process in report["processes"]:
            print(
                f"\n{process['title']} [{process['algorithm']}] — "
                f"{process['totalDraws']} draws"
            )
            support = process["meanFinalModelSupportBasisPoints"]
            print(
                "  mean final support: "
                + ", ".join(
                    f"{model}={basis_points / 100:.2f}%"
                    for model, basis_points in support.items()
                )
            )
            occupancy = process["stateOccupancy"]
            print(
                "  latent occupancy: "
                + ", ".join(
                    f"{state}={data['percent']:.2f}%"
                    for state, data in occupancy.items()
                )
            )
        print("\nRoute audit:", "PASS" if report["ok"] else "FAIL")
        for position in report["routeAudit"]:
            print(
                f"  Position {position['ordinal']} {position['positionId']}: "
                f"{position['routeCount']} routes"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
