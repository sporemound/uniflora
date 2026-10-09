from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dynamical_map import (
    DYNAMICAL_LAYERS,
    DynamicalMapError,
    MapBounds,
    fetch_and_export_dynamical_overlay,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATIC_OUTPUT = ROOT.parent / "activity" / "public" / "data" / "dynamical"
STATIC_INDEX_FILENAME = "manifest.json"
FRONTEND_MANIFEST_KEYS = (
    "datasetId",
    "kind",
    "url",
    "coordinates",
    "generatedAt",
    "validTime",
    "variable",
    "units",
    "attribution",
    "status",
)
FULL_DOMAIN_BOUNDS = {
    "dynamical-asos": MapBounds(-179.5, -85, 179.5, 85),
    "dynamical-gfs-analysis": MapBounds(-179.5, -85, 179.5, 85),
    "dynamical-hrrr-analysis": MapBounds(-134, 20, -60, 54),
    "dynamical-mrms-analysis": MapBounds(-129.995, 20.005, -60.005, 54.995),
    "dynamical-imerg-late": MapBounds(-179.5, -85, 179.5, 85),
}


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _bounds(values: list[float]) -> MapBounds:
    try:
        return MapBounds(*values)
    except DynamicalMapError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        suffix=".json",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(encoded)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _export_one(args: argparse.Namespace) -> int:
    if args.bounds is None:
        raise DynamicalMapError("--bounds is required when exporting one layer")
    layer_id = args.dataset
    image_filename = f"{layer_id}.png"
    manifest_filename = f"{layer_id}.json"
    bundle = fetch_and_export_dynamical_overlay(
        layer_id=layer_id,
        variable=args.variable,
        requested_time=args.valid_time,
        bounds=args.bounds,
        output_directory=args.output,
        generated_at=args.generated_at,
        public_url=f"/data/dynamical/{image_filename}",
        width=args.width,
        height=args.height,
    )
    # The single-layer producer uses stable Activity filenames too.
    if bundle.image_path.name != image_filename:
        target = bundle.image_path.with_name(image_filename)
        os.replace(bundle.image_path, target)
        bundle.manifest["image"]["filename"] = image_filename
        bundle.manifest["url"] = f"/data/dynamical/{image_filename}"
        _atomic_json(bundle.manifest_path.with_name(manifest_filename), bundle.manifest)
        bundle.manifest_path.unlink(missing_ok=True)
    print(json.dumps(bundle.manifest, indent=2, sort_keys=True))
    return 0


def _export_static(args: argparse.Namespace) -> int:
    layers: dict[str, dict[str, Any]] = {}
    for layer_id, definition in DYNAMICAL_LAYERS.items():
        image_filename = f"{layer_id}.png"
        manifest_filename = f"{layer_id}.json"
        bundle = fetch_and_export_dynamical_overlay(
            layer_id=layer_id,
            variable=None,
            requested_time=args.valid_time,
            bounds=FULL_DOMAIN_BOUNDS[layer_id],
            output_directory=args.output,
            generated_at=args.generated_at,
            public_url=f"/data/dynamical/{image_filename}",
            width=args.width,
            height=args.height,
        )
        image_target = args.output / image_filename
        manifest_target = args.output / manifest_filename
        os.replace(bundle.image_path, image_target)
        bundle.manifest["image"]["filename"] = image_filename
        bundle.manifest["url"] = f"/data/dynamical/{image_filename}"
        _atomic_json(manifest_target, bundle.manifest)
        bundle.manifest_path.unlink(missing_ok=True)
        layers[layer_id] = {
            key: bundle.manifest[key]
            for key in FRONTEND_MANIFEST_KEYS
        }
        print(
            f"rendered {definition.catalog_id} {bundle.manifest['variable']} "
            f"at {bundle.manifest['validTime']}"
        )
    index = {
        "schemaVersion": 1,
        "generatedAt": args.generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "layers": layers,
    }
    _atomic_json(args.output / STATIC_INDEX_FILENAME, index)
    print(json.dumps(index, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch real Dynamical weather data and export transparent HoloViews overlays "
            "for the Discord Activity base map."
        )
    )
    parser.add_argument(
        "--dataset",
        choices=[*DYNAMICAL_LAYERS, "all"],
        required=True,
        help="Activity dataset ID, or 'all' for the canonical static index.",
    )
    parser.add_argument("--valid-time", type=_timestamp, required=True)
    parser.add_argument(
        "--generated-at",
        type=_timestamp,
        default=datetime.now(UTC),
        help="Manifest generation time; defaults to now.",
    )
    parser.add_argument(
        "--bounds",
        type=float,
        nargs=4,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="Required for one layer; static all-layer export uses catalog domains.",
    )
    parser.add_argument("--variable", help="Dataset variable; defaults by layer.")
    parser.add_argument("--output", type=Path, default=DEFAULT_STATIC_OUTPUT)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.bounds is not None:
        try:
            args.bounds = _bounds(args.bounds)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
    if args.dataset == "all":
        if args.bounds is not None:
            parser.error("--bounds cannot be combined with --dataset all")
        if args.variable is not None:
            parser.error("--variable cannot be combined with --dataset all")
        return _export_static(args)
    if args.bounds is None:
        parser.error("--bounds is required unless --dataset all is selected")
    return _export_one(args)


if __name__ == "__main__":
    raise SystemExit(main())
