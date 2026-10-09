from __future__ import annotations

import argparse
from pathlib import Path

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.cycles import initial_cycle
from uniflora.summary_chart import (
    SummarySnapshot,
    attachment_filename,
    convert_svg_to_png,
    normalize_chart_state,
    render_summary_svg,
)


def build_fixture_snapshot() -> SummarySnapshot:
    registry = PuzzleRegistry.load_packaged()
    definition = registry.get(1)
    data = definition.initial_state()
    data["cycle"] = initial_cycle(1)
    data["cycle"].update(
        {
            "primary_contributors": {
                "fixture:observer": {"action": "observe", "function": "observer"},
                "fixture:carrier": {"action": "sustain", "function": "carrier"},
            },
            "observation_count": 3,
        }
    )
    data["prior_position_summary"] = (
        "Position 0 preserved Eastern viability, Northern reserve, and repaired Route 03; "
        "the formerly separate regions now resolve as civic systems in one workers’ settlement."
    )
    data["confirmed_facts"] = [
        {
            "public_text": (
                "Lower Archive may donate modestly, but falling below 5 water suspends "
                "coherence."
            ),
            "classification": "confirmed",
        },
        {
            "public_text": (
                "The Condensation Veil can provide 9 water during this cycle if maintained."
            ),
            "classification": "confirmed",
        },
    ]
    data["triggered_reactions"] = [
        {
            "trigger_id": "fixture-northern-risk",
            "public_trigger_id": "risk-check-northern-reservoir",
            "kind": "risk_check",
            "observation_id": "northern_inherited_burden",
            "consumed": False,
        }
    ]
    data["counters"] = {
        "strain": {"northern_reservoir": 1},
        "repair": {"damaged_circulation": 1},
        "viability": {"return_indicator_bed": 3},
        "containment": 2,
    }
    data["exterior_weather"] = {
        "type": "exterior_weather_observed",
        "environment": "fixture",
        "deduplication_key": "fixture-heca-20260722-201322",
        "station": "HECA",
        "station_scope": "regional_relay",
        "source": "aprs.fi",
        "observed_at": "2026-07-22T20:13:22+00:00",
        "phase": "night",
        "phase_lore": "cold-sky collection and protected storage",
        "local_observed_at": "2026-07-22T23:13:22+03:00",
        "window_expires_at": "2026-07-22T22:13:22+00:00",
        "local_window_expires_at": "2026-07-23T01:13:22+03:00",
        "readings": {
            "temperature_c": 30.6,
            "pressure_mbar": 1009.0,
            "humidity_percent": 52.0,
            "wind_direction_degrees": 310.0,
            "wind_speed_mps": 4.9,
            "wind_gust_mps": None,
            "rain_1h_mm": None,
            "rain_24h_mm": None,
            "rain_since_midnight_mm": None,
            "luminosity_wm2": None,
        },
        "signal_scores": {
            "exterior_pressure": 0.1202,
        },
        "conditions": ["nominal"],
        "water_system_multipliers": {
            "condensation_veil_multiplier": 1.1430,
            "solar_distillation_multiplier": 0.7285,
            "cistern_retention_multiplier": 1.0357,
            "capillary_transfer_multiplier": 1.0309,
            "wind_tower_multiplier": 0.9980,
            "thermal_storage_multiplier": 1.0458,
            "water_purity_multiplier": 0.9984,
            "evaporation_burden_multiplier": 0.9227,
            "exterior_pressure_score": 0.1202,
        },
        "eligible_triggers": [
            {
                "kind": "condensation_window",
                "severity": 1,
                "reason": (
                    "the cold-sky veil has entered a favorable "
                    "collection window"
                ),
                "requires_player_action": False,
                "once_per_cycle": True,
            }
        ],
        "replacement_semantics": (
            "replace active weather influence; never stack"
        ),
        "duplicate": False,
        "notes": ["pressure and trend baseline established"],
    }

    session_state = {
        "mode": "running",
        "current_position": 1,
        "response_profile": "surface_noise",
        "data": data,
        "modified_by_force": False,
        "version": 1,
    }
    return SummarySnapshot.capture(
        environment="fixture",
        session_state=session_state,
        definition=definition.model_dump(mode="json"),
        public_resource_lines=(
            "Condensation Veil: current-cycle output 9 water; maintenance required before use",
            "Lower Archive: current 7 water; coherence floor 5; donation headroom 2",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the developer game-state summary fixture without Discord."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("render-output"),
        help="Ignored output directory (default: render-output)",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    snapshot = build_fixture_snapshot()
    svg = render_summary_svg(normalize_chart_state(snapshot))
    png = convert_svg_to_png(svg)
    stem = attachment_filename(snapshot).removesuffix(".png")
    svg_path = args.output_dir / f"{stem}.svg"
    png_path = args.output_dir / f"{stem}.png"
    svg_path.write_text(svg, encoding="utf-8")
    png_path.write_bytes(png)
    print(f"Wrote {svg_path}")
    print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
