from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from uniflora.engine.v2.analysis import analysis_input_to_record
from uniflora.engine.v2.analysis_dataset import V2LocalAnalysisDatasetRepository
from uniflora.engine.v2.analysis_persistence import V2SQLiteAnalysisStore
from uniflora.engine.v2.analysis_worker import (
    V2AnalysisMethodRegistry,
    V2AnalysisWorker,
    V2AnalysisWorkerError,
)
from uniflora.engine.v2.serialization import canonical_json_bytes

RegistryFactory = Callable[[], V2AnalysisMethodRegistry]


def _positive_seconds(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m uniflora.engine.v2.analysis_cli",
        description=(
            "Import retained datasets or execute one leased v2 analysis job "
            "outside the Discord process."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    import_parser = subcommands.add_parser(
        "import-dataset",
        help="atomically import a local file into the retained dataset repository",
    )
    import_parser.add_argument("--repository", required=True, type=Path)
    import_parser.add_argument("--file", required=True, type=Path)
    import_parser.add_argument("--dataset-id", required=True)
    import_parser.add_argument("--source-evidence-id", required=True)
    import_parser.add_argument("--media-type", required=True)
    import_parser.add_argument("--provenance", required=True)
    import_parser.add_argument(
        "--preprocessing-step",
        action="append",
        default=[],
        help="repeat for each completed preprocessing step",
    )

    list_parser = subcommands.add_parser(
        "list-datasets",
        help="verify and list retained dataset descriptors",
    )
    list_parser.add_argument("--repository", required=True, type=Path)

    run_parser = subcommands.add_parser(
        "run-once",
        help="claim and execute at most one persisted analysis job",
    )
    run_parser.add_argument("--database", required=True, type=Path)
    run_parser.add_argument("--repository", required=True, type=Path)
    run_parser.add_argument("--registry-factory", required=True)
    run_parser.add_argument(
        "--worker-id",
        default=f"local-{os.getpid()}",
    )
    run_parser.add_argument(
        "--lease-seconds",
        type=_positive_seconds,
        default=300.0,
    )

    return parser


def _write_json(stream: TextIO, value: object) -> None:
    stream.write(canonical_json_bytes(value).decode("utf-8"))
    stream.write("\n")


def _load_registry_factory(specification: str) -> RegistryFactory:
    module_name, separator, attribute_name = specification.partition(":")
    if not separator or not module_name.strip() or not attribute_name.strip():
        raise ValueError("registry factory must use the form 'module.path:callable_name'")

    module = importlib.import_module(module_name.strip())
    factory = getattr(module, attribute_name.strip(), None)
    if not callable(factory):
        raise ValueError("registry factory target is not callable")
    return factory


def _registry(specification: str) -> V2AnalysisMethodRegistry:
    factory = _load_registry_factory(specification)
    registry = factory()
    if not isinstance(registry, V2AnalysisMethodRegistry):
        raise TypeError("registry factory must return V2AnalysisMethodRegistry")
    return registry


def _run_import(arguments: argparse.Namespace, *, stdout: TextIO) -> int:
    repository = V2LocalAnalysisDatasetRepository(arguments.repository)
    stored = repository.import_file(
        arguments.file,
        dataset_id=arguments.dataset_id,
        source_evidence_id=arguments.source_evidence_id,
        media_type=arguments.media_type,
        provenance=arguments.provenance,
        preprocessing_steps=tuple(arguments.preprocessing_step),
    )
    _write_json(stdout, analysis_input_to_record(stored.descriptor))
    return 0


def _run_list(arguments: argparse.Namespace, *, stdout: TextIO) -> int:
    repository = V2LocalAnalysisDatasetRepository(arguments.repository)
    _write_json(
        stdout,
        [analysis_input_to_record(stored.descriptor) for stored in repository.list_datasets()],
    )
    return 0


def _run_once(arguments: argparse.Namespace, *, stdout: TextIO) -> int:
    repository = V2LocalAnalysisDatasetRepository(arguments.repository)
    registry = _registry(arguments.registry_factory)

    arguments.database.parent.mkdir(parents=True, exist_ok=True)
    with V2SQLiteAnalysisStore(arguments.database) as store:
        outcome = V2AnalysisWorker(
            store=store,
            registry=registry,
            dataset_resolver=repository,
            worker_id=arguments.worker_id,
            lease_duration=timedelta(seconds=arguments.lease_seconds),
        ).run_once()

    _write_json(
        stdout,
        {
            "artifact_id": outcome.artifact_id,
            "attempt_count": outcome.attempt_count,
            "error": outcome.error,
            "job_id": outcome.job_id,
            "status": outcome.status.value,
        },
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = _parser()

    try:
        arguments = parser.parse_args(argv)
        if arguments.command == "import-dataset":
            return _run_import(arguments, stdout=output)
        if arguments.command == "list-datasets":
            return _run_list(arguments, stdout=output)
        if arguments.command == "run-once":
            return _run_once(arguments, stdout=output)
        parser.error(f"unsupported command: {arguments.command}")
    except (
        ImportError,
        OSError,
        TypeError,
        ValueError,
        V2AnalysisWorkerError,
    ) as exc:
        errors.write(f"error: {exc}\n")
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
