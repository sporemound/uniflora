from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .export import export_publication_bundle
from .io import load_signal_frame
from .models import load_artifact

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT = ROOT / "examples" / "sr03-artifact.json"
DEFAULT_OUTPUT = ROOT / "data" / "rendered"


def serve(args: argparse.Namespace) -> int:
    environment = os.environ.copy()
    environment["MI_DASHBOARD_ARTIFACT"] = str(args.artifact.resolve())
    command = [
        sys.executable,
        "-m",
        "panel",
        "serve",
        str(ROOT / "app.py"),
        "--address",
        args.address,
        "--port",
        str(args.port),
        "--show" if args.show else "--reuse-sessions",
    ]
    if args.dev:
        command.append("--dev")
    print("Running:")
    print("  " + subprocess.list2cmdline(command))
    return subprocess.run(command, env=environment, check=False).returncode


def export(args: argparse.Namespace) -> int:
    artifact = load_artifact(args.artifact)
    frame = load_signal_frame(args.artifact, artifact)
    bundle = export_publication_bundle(artifact, frame, args.output)
    print(
        json.dumps(
            {
                "visualization_id": bundle.visualization_id,
                "directory": str(bundle.directory),
                "svg": str(bundle.svg_path),
                "png": str(bundle.png_path),
                "manifest": str(bundle.manifest_path),
                "activity_publication": str(bundle.activity_publication_path),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or export the isolated Phase 3 scientific dashboard."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve_parser = commands.add_parser("serve", help="Run the local Panel/HoloViews dashboard.")
    serve_parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    serve_parser.add_argument("--address", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--show", action=argparse.BooleanOptionalAction, default=True)
    serve_parser.add_argument("--dev", action="store_true")
    serve_parser.set_defaults(handler=serve)

    export_parser = commands.add_parser(
        "export", help="Create a deterministic SVG-to-PNG publication bundle."
    )
    export_parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    export_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    export_parser.set_defaults(handler=export)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.artifact.is_file():
        parser.error(f"Artifact does not exist: {args.artifact}")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
