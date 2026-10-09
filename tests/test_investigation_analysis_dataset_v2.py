from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest

import uniflora.engine.v2.analysis_dataset as dataset_module
from uniflora.engine.v2 import (
    V2AnalysisDatasetConflictError,
    V2AnalysisDatasetIntegrityError,
    V2AnalysisDatasetNotFoundError,
    V2AnalysisDerivedValue,
    V2AnalysisExecutionResult,
    V2AnalysisInput,
    V2AnalysisInputIntegrityError,
    V2AnalysisJob,
    V2AnalysisJobStatus,
    V2AnalysisMethod,
    V2AnalysisMethodRegistry,
    V2AnalysisParameter,
    V2AnalysisUncertainty,
    V2AnalysisWorker,
    V2AnalysisWorkerOutcomeStatus,
    V2LocalAnalysisDatasetRepository,
    V2SoftwareVersion,
    V2SQLiteAnalysisStore,
    calculate_dataset_hash,
    create_analysis_job_envelope,
)
from uniflora.engine.v2.analysis_cli import main as analysis_cli_main

PAYLOAD = b"retained boundary-array bytes\n"
BASE_TIME = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)


def _import(
    repository: V2LocalAnalysisDatasetRepository,
    *,
    dataset_id: str = "boundary_optical_record",
    payload: bytes = PAYLOAD,
    provenance: str = "Copied from the retained Boundary Array export.",
):
    return repository.import_bytes(
        payload,
        dataset_id=dataset_id,
        source_evidence_id="optical_record",
        media_type="application/octet-stream",
        provenance=provenance,
        preprocessing_steps=("container headers removed",),
    )


def _method() -> V2AnalysisMethod:
    return V2AnalysisMethod(
        method_id="byte_count",
        version="1.0.0",
        implementation="tests.byte_count",
        description="Count retained input bytes.",
    )


def _result(request) -> V2AnalysisExecutionResult:
    payload = request.inputs[0].data
    return V2AnalysisExecutionResult(
        derived_values=(
            V2AnalysisDerivedValue.from_value(
                "byte_count",
                len(payload),
                unit="bytes",
            ),
        ),
        uncertainties=(
            V2AnalysisUncertainty(
                source="semantic_scope",
                statement="Byte count does not interpret the record.",
            ),
        ),
        limitations=("No scientific meaning is inferred from byte length.",),
        software_versions=(V2SoftwareVersion(name="test-worker", version="1.0.0"),),
        provenance=("Executed from retained content-addressed bytes.",),
    )


def _registry() -> V2AnalysisMethodRegistry:
    registry = V2AnalysisMethodRegistry()
    registry.register(_method(), _result)
    return registry


def _job(descriptor: V2AnalysisInput):
    return create_analysis_job_envelope(
        V2AnalysisJob(
            job_id="job_byte_count",
            stream_id="investigation_alpha",
            position_id="boundary_event",
            requested_by_player_id="player_a",
            method=_method(),
            inputs=(descriptor,),
            parameters=(V2AnalysisParameter.from_value("strict", True),),
            output_kind="byte_count_report",
        )
    )


def test_repository_imports_and_resolves_exact_retained_bytes(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository)

    assert stored.object_path.is_file()
    assert stored.manifest_path.is_file()
    assert stored.descriptor.content_hash == calculate_dataset_hash(PAYLOAD)
    assert repository.resolve(stored.descriptor) == PAYLOAD


def test_repository_import_is_idempotent_for_the_same_descriptor(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")

    first = _import(repository)
    second = _import(repository)

    assert second == first
    assert len(repository.list_datasets()) == 1


def test_repository_deduplicates_identical_bytes_across_dataset_ids(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")

    first = _import(repository, dataset_id="first")
    second = _import(repository, dataset_id="second")

    assert first.object_path == second.object_path
    assert first.manifest_path != second.manifest_path
    assert tuple(item.dataset_id for item in repository.list_datasets()) == (
        "first",
        "second",
    )


def test_repository_rejects_dataset_id_reuse_with_different_bytes(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    _import(repository)

    with pytest.raises(V2AnalysisDatasetConflictError, match="already retained"):
        _import(repository, payload=b"different")


def test_repository_rejects_dataset_id_reuse_with_metadata_drift(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    _import(repository)

    with pytest.raises(V2AnalysisDatasetConflictError, match="different metadata"):
        _import(repository, provenance="Changed provenance.")


def test_dataset_ids_cannot_escape_the_manifest_directory(tmp_path) -> None:
    root = tmp_path / "datasets"
    repository = V2LocalAnalysisDatasetRepository(root)

    stored = _import(repository, dataset_id="../../outside")

    assert stored.manifest_path.parent == root / "datasets"
    assert stored.manifest_path.name.endswith(".json")
    assert "outside" not in stored.manifest_path.name


def test_repository_imports_a_file_without_rewriting_the_source(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")

    stored = repository.import_file(
        source,
        dataset_id="file_import",
        source_evidence_id="radio_return",
        media_type="application/octet-stream",
        provenance="Retained receiver export.",
    )

    assert source.read_bytes() == PAYLOAD
    assert repository.resolve(stored.descriptor) == PAYLOAD


def test_repository_accepts_an_exact_zero_byte_dataset(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository, payload=b"")

    assert stored.descriptor.byte_length == 0
    assert repository.resolve(stored.descriptor) == b""


def test_repository_reports_a_missing_dataset(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")

    with pytest.raises(V2AnalysisDatasetNotFoundError):
        repository.get("missing")


def test_repository_rejects_a_job_descriptor_that_does_not_exactly_match(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository)
    changed = V2AnalysisInput(
        dataset_id=stored.dataset_id,
        source_evidence_id="different_evidence",
        content_hash=stored.descriptor.content_hash,
        byte_length=stored.descriptor.byte_length,
        media_type=stored.descriptor.media_type,
        provenance=stored.descriptor.provenance,
        preprocessing_steps=stored.descriptor.preprocessing_steps,
    )

    with pytest.raises(V2AnalysisInputIntegrityError, match="does not exactly match"):
        repository.resolve(changed)


def test_repository_detects_tampered_object_bytes(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository)
    stored.object_path.write_bytes(b"tampered")

    with pytest.raises(V2AnalysisDatasetIntegrityError, match="byte length|hash"):
        repository.get(stored.dataset_id)


def test_repository_detects_noncanonical_manifest_encoding(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository)
    record = json.loads(stored.manifest_path.read_text(encoding="utf-8"))
    stored.manifest_path.write_text(
        json.dumps(record, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(V2AnalysisDatasetIntegrityError, match="canonically"):
        repository.get(stored.dataset_id)


def test_repository_detects_manifest_filename_mismatch(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    stored = _import(repository)
    record = json.loads(stored.manifest_path.read_text(encoding="utf-8"))
    record["descriptor"]["dataset_id"] = "another_dataset"
    stored.manifest_path.write_bytes(dataset_module.canonical_json_bytes(record))

    with pytest.raises(V2AnalysisDatasetIntegrityError, match="filename"):
        repository.get(stored.dataset_id)


def test_failed_manifest_commit_leaves_no_partial_manifest(tmp_path, monkeypatch) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")

    def fail_write(path: Path, payload: bytes) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(dataset_module, "_write_atomic", fail_write)
    with pytest.raises(OSError, match="interruption"):
        _import(repository)

    assert not tuple((repository.root / "datasets").glob("*.json"))


def test_list_datasets_verifies_objects_and_sorts_by_dataset_id(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "datasets")
    _import(repository, dataset_id="zeta")
    _import(repository, dataset_id="alpha")

    assert tuple(item.dataset_id for item in repository.list_datasets()) == (
        "alpha",
        "zeta",
    )


def test_cli_import_dataset_emits_canonical_descriptor_json(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    stdout = StringIO()
    stderr = StringIO()

    result = analysis_cli_main(
        [
            "import-dataset",
            "--repository",
            str(tmp_path / "repository"),
            "--file",
            str(source),
            "--dataset-id",
            "cli_dataset",
            "--source-evidence-id",
            "optical_record",
            "--media-type",
            "application/octet-stream",
            "--provenance",
            "CLI import test.",
            "--preprocessing-step",
            "headers removed",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    record = json.loads(stdout.getvalue())
    assert result == 0
    assert stderr.getvalue() == ""
    assert record["dataset_id"] == "cli_dataset"
    assert record["content_hash"] == calculate_dataset_hash(PAYLOAD)


def test_cli_list_datasets_emits_verified_sorted_records(tmp_path) -> None:
    repository_path = tmp_path / "repository"
    repository = V2LocalAnalysisDatasetRepository(repository_path)
    _import(repository, dataset_id="second")
    _import(repository, dataset_id="first")
    stdout = StringIO()

    result = analysis_cli_main(
        ["list-datasets", "--repository", str(repository_path)],
        stdout=stdout,
        stderr=StringIO(),
    )

    records = json.loads(stdout.getvalue())
    assert result == 0
    assert [record["dataset_id"] for record in records] == ["first", "second"]


def test_cli_run_once_executes_one_job_from_the_local_repository(tmp_path) -> None:
    repository_path = tmp_path / "repository"
    database_path = tmp_path / "analysis.sqlite3"
    repository = V2LocalAnalysisDatasetRepository(repository_path)
    stored = _import(repository)
    envelope = _job(stored.descriptor)

    with V2SQLiteAnalysisStore(database_path) as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)

    module = ModuleType("v2_test_registry")

    def create_registry() -> V2AnalysisMethodRegistry:
        registry = V2AnalysisMethodRegistry()
        registry.register(_method(), _result)
        return registry

    module.create_registry = create_registry
    sys.modules[module.__name__] = module
    stdout = StringIO()
    stderr = StringIO()
    try:
        result = analysis_cli_main(
            [
                "run-once",
                "--database",
                str(database_path),
                "--repository",
                str(repository_path),
                "--registry-factory",
                "v2_test_registry:create_registry",
                "--worker-id",
                "cli_worker",
                "--lease-seconds",
                "60",
            ],
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        sys.modules.pop(module.__name__, None)

    record = json.loads(stdout.getvalue())
    assert result == 0
    assert stderr.getvalue() == ""
    assert record["status"] == "completed"
    assert record["job_id"] == envelope.job.job_id

    with V2SQLiteAnalysisStore(database_path) as store:
        assert store.get_job(envelope.job.job_id).status is V2AnalysisJobStatus.COMPLETED
        assert store.get_artifact_for_job(envelope.job.job_id) is not None


def test_cli_run_once_reports_idle_as_machine_readable_json(tmp_path) -> None:
    module = ModuleType("v2_empty_registry")
    module.create_registry = V2AnalysisMethodRegistry
    sys.modules[module.__name__] = module
    stdout = StringIO()
    try:
        result = analysis_cli_main(
            [
                "run-once",
                "--database",
                str(tmp_path / "analysis.sqlite3"),
                "--repository",
                str(tmp_path / "repository"),
                "--registry-factory",
                "v2_empty_registry:create_registry",
            ],
            stdout=stdout,
            stderr=StringIO(),
        )
    finally:
        sys.modules.pop(module.__name__, None)

    assert result == 0
    assert json.loads(stdout.getvalue()) == {
        "artifact_id": None,
        "attempt_count": None,
        "error": None,
        "job_id": None,
        "status": "idle",
    }


def test_cli_reports_bad_registry_configuration_without_a_traceback(tmp_path) -> None:
    stderr = StringIO()

    result = analysis_cli_main(
        [
            "run-once",
            "--database",
            str(tmp_path / "analysis.sqlite3"),
            "--repository",
            str(tmp_path / "repository"),
            "--registry-factory",
            "missing_separator",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 2
    assert stderr.getvalue().startswith("error:")
    assert "Traceback" not in stderr.getvalue()


def test_worker_requeues_a_job_when_retained_bytes_are_not_imported(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "repository")
    descriptor = V2AnalysisInput(
        dataset_id="not_imported",
        source_evidence_id="optical_record",
        content_hash=calculate_dataset_hash(PAYLOAD),
        byte_length=len(PAYLOAD),
        media_type="application/octet-stream",
        provenance="Expected retained bytes.",
    )
    envelope = _job(descriptor)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = V2AnalysisWorker(
            store=store,
            registry=_registry(),
            dataset_resolver=repository,
            worker_id="repository_worker",
            lease_duration=timedelta(minutes=1),
        ).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.RETRY_QUEUED
    assert "does not exist" in (outcome.error or "")


def test_worker_fails_terminally_when_retained_bytes_are_tampered(tmp_path) -> None:
    repository = V2LocalAnalysisDatasetRepository(tmp_path / "repository")
    stored = _import(repository)
    stored.object_path.write_bytes(b"tampered")
    envelope = _job(stored.descriptor)

    with V2SQLiteAnalysisStore(tmp_path / "analysis.sqlite3") as store:
        store.enqueue_job(envelope, submitted_at=BASE_TIME)
        outcome = V2AnalysisWorker(
            store=store,
            registry=_registry(),
            dataset_resolver=repository,
            worker_id="repository_worker",
            lease_duration=timedelta(minutes=1),
        ).run_once()

    assert outcome.status is V2AnalysisWorkerOutcomeStatus.FAILED
    assert "byte length" in (outcome.error or "") or "hash" in (outcome.error or "")
