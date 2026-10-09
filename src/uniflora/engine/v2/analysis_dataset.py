from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from uniflora.engine.v2.analysis import (
    V2AnalysisError,
    V2AnalysisInput,
    analysis_input_from_record,
    analysis_input_to_record,
    calculate_dataset_hash,
)
from uniflora.engine.v2.analysis_worker import (
    V2AnalysisDatasetResolutionError,
    V2AnalysisInputIntegrityError,
)
from uniflora.engine.v2.serialization import canonical_json_bytes

V2_ANALYSIS_DATASET_MANIFEST_SCHEMA_VERSION = 1
_COPY_CHUNK_SIZE = 1024 * 1024


class V2AnalysisDatasetRepositoryError(ValueError):
    """Raised when retained analysis datasets cannot be stored or resolved safely."""


class V2AnalysisDatasetNotFoundError(V2AnalysisDatasetRepositoryError):
    """Raised when a dataset ID has no retained manifest in the repository."""


class V2AnalysisDatasetConflictError(V2AnalysisDatasetRepositoryError):
    """Raised when a dataset ID is reused with different retained metadata."""


class V2AnalysisDatasetIntegrityError(V2AnalysisDatasetRepositoryError):
    """Raised when retained manifests or object bytes fail integrity checks."""


def _require_nonblank(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


def _manifest_key(dataset_id: str) -> str:
    normalized = _require_nonblank(dataset_id, label="dataset ID")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class V2StoredAnalysisDataset:
    descriptor: V2AnalysisInput
    object_path: Path
    manifest_path: Path

    @property
    def dataset_id(self) -> str:
        return self.descriptor.dataset_id


class V2LocalAnalysisDatasetRepository:
    """Content-addressed retained-byte repository for standalone analysis workers."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._objects = self._root / "objects" / "sha256"
        self._manifests = self._root / "datasets"
        self._temporary = self._root / "tmp"

        self._objects.mkdir(parents=True, exist_ok=True)
        self._manifests.mkdir(parents=True, exist_ok=True)
        self._temporary.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _object_path(self, content_hash: str) -> Path:
        if (
            len(content_hash) != 64
            or content_hash.lower() != content_hash
            or any(character not in "0123456789abcdef" for character in content_hash)
        ):
            raise V2AnalysisDatasetIntegrityError(
                "dataset content hash is not a canonical SHA-256 digest"
            )
        return self._objects / content_hash[:2] / content_hash[2:]

    def _manifest_path(self, dataset_id: str) -> Path:
        return self._manifests / f"{_manifest_key(dataset_id)}.json"

    def _manifest_bytes(self, descriptor: V2AnalysisInput) -> bytes:
        return canonical_json_bytes(
            {
                "descriptor": analysis_input_to_record(descriptor),
                "schema_version": V2_ANALYSIS_DATASET_MANIFEST_SCHEMA_VERSION,
            }
        )

    def _read_manifest_path(self, path: Path) -> V2AnalysisInput:
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise V2AnalysisDatasetNotFoundError(
                f"analysis dataset manifest does not exist: {path.name}"
            ) from exc
        except OSError as exc:
            raise V2AnalysisDatasetRepositoryError(
                f"analysis dataset manifest could not be read: {path.name}"
            ) from exc

        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise V2AnalysisDatasetIntegrityError(
                f"analysis dataset manifest is not valid canonical JSON: {path.name}"
            ) from exc

        if not isinstance(record, dict) or set(record) != {
            "descriptor",
            "schema_version",
        }:
            raise V2AnalysisDatasetIntegrityError(
                f"analysis dataset manifest has an invalid structure: {path.name}"
            )

        if record["schema_version"] != V2_ANALYSIS_DATASET_MANIFEST_SCHEMA_VERSION:
            raise V2AnalysisDatasetIntegrityError(
                f"unsupported analysis dataset manifest schema: {record['schema_version']!r}"
            )

        try:
            descriptor = analysis_input_from_record(record["descriptor"])
        except (V2AnalysisError, TypeError, ValueError) as exc:
            raise V2AnalysisDatasetIntegrityError(
                f"analysis dataset manifest contains an invalid descriptor: {path.name}"
            ) from exc

        expected_path = self._manifest_path(descriptor.dataset_id)
        if expected_path.name != path.name:
            raise V2AnalysisDatasetIntegrityError(
                "analysis dataset manifest filename does not match its dataset ID"
            )

        if canonical_json_bytes(record) != raw:
            raise V2AnalysisDatasetIntegrityError(
                f"analysis dataset manifest is not canonically encoded: {path.name}"
            )

        return descriptor

    def _verify_object(self, descriptor: V2AnalysisInput) -> Path:
        object_path = self._object_path(descriptor.content_hash)
        try:
            handle = object_path.open("rb")
        except FileNotFoundError as exc:
            raise V2AnalysisDatasetIntegrityError(
                f"retained bytes are missing for dataset {descriptor.dataset_id!r}"
            ) from exc
        except OSError as exc:
            raise V2AnalysisDatasetRepositoryError(
                f"retained bytes could not be opened for dataset {descriptor.dataset_id!r}"
            ) from exc

        digest = hashlib.sha256()
        byte_length = 0
        with handle:
            while chunk := handle.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
                byte_length += len(chunk)

        if byte_length != descriptor.byte_length:
            raise V2AnalysisDatasetIntegrityError(
                f"retained byte length does not match dataset {descriptor.dataset_id!r}"
            )
        if digest.hexdigest() != descriptor.content_hash:
            raise V2AnalysisDatasetIntegrityError(
                f"retained byte hash does not match dataset {descriptor.dataset_id!r}"
            )

        return object_path

    def _commit_object(self, temporary_path: Path, descriptor: V2AnalysisInput) -> Path:
        object_path = self._object_path(descriptor.content_hash)
        object_path.parent.mkdir(parents=True, exist_ok=True)

        if object_path.exists():
            temporary_path.unlink(missing_ok=True)
            return self._verify_object(descriptor)

        try:
            os.replace(temporary_path, object_path)
            _fsync_directory(object_path.parent)
        except OSError as exc:
            raise V2AnalysisDatasetRepositoryError(
                f"retained bytes could not be committed for dataset {descriptor.dataset_id!r}"
            ) from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        return self._verify_object(descriptor)

    def _commit_manifest(self, descriptor: V2AnalysisInput) -> Path:
        manifest_path = self._manifest_path(descriptor.dataset_id)

        if manifest_path.exists():
            retained = self._read_manifest_path(manifest_path)
            if retained != descriptor:
                raise V2AnalysisDatasetConflictError(
                    f"dataset ID {descriptor.dataset_id!r} is already retained "
                    "with different metadata or content"
                )
            return manifest_path

        _write_atomic(manifest_path, self._manifest_bytes(descriptor))
        retained = self._read_manifest_path(manifest_path)
        if retained != descriptor:
            raise V2AnalysisDatasetConflictError(
                f"dataset ID {descriptor.dataset_id!r} was concurrently retained "
                "with different metadata or content"
            )
        return manifest_path

    def _descriptor(
        self,
        *,
        dataset_id: str,
        source_evidence_id: str,
        content_hash: str,
        byte_length: int,
        media_type: str,
        provenance: str,
        preprocessing_steps: tuple[str, ...],
    ) -> V2AnalysisInput:
        return V2AnalysisInput(
            dataset_id=dataset_id,
            source_evidence_id=source_evidence_id,
            content_hash=content_hash,
            byte_length=byte_length,
            media_type=media_type,
            provenance=provenance,
            preprocessing_steps=preprocessing_steps,
        )

    def import_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        dataset_id: str,
        source_evidence_id: str,
        media_type: str,
        provenance: str,
        preprocessing_steps: tuple[str, ...] = (),
    ) -> V2StoredAnalysisDataset:
        payload = bytes(data)
        descriptor = self._descriptor(
            dataset_id=dataset_id,
            source_evidence_id=source_evidence_id,
            content_hash=calculate_dataset_hash(payload),
            byte_length=len(payload),
            media_type=media_type,
            provenance=provenance,
            preprocessing_steps=tuple(preprocessing_steps),
        )

        descriptor_fd, descriptor_name = tempfile.mkstemp(
            prefix="dataset-",
            suffix=".tmp",
            dir=self._temporary,
        )
        temporary_path = Path(descriptor_name)
        try:
            with os.fdopen(descriptor_fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            object_path = self._commit_object(temporary_path, descriptor)
            manifest_path = self._commit_manifest(descriptor)
        finally:
            temporary_path.unlink(missing_ok=True)

        return V2StoredAnalysisDataset(
            descriptor=descriptor,
            object_path=object_path,
            manifest_path=manifest_path,
        )

    def import_file(
        self,
        source: str | Path,
        *,
        dataset_id: str,
        source_evidence_id: str,
        media_type: str,
        provenance: str,
        preprocessing_steps: tuple[str, ...] = (),
    ) -> V2StoredAnalysisDataset:
        source_path = Path(source)
        if not source_path.is_file():
            raise V2AnalysisDatasetNotFoundError(
                f"dataset source file does not exist: {source_path}"
            )

        descriptor_fd, descriptor_name = tempfile.mkstemp(
            prefix="dataset-",
            suffix=".tmp",
            dir=self._temporary,
        )
        temporary_path = Path(descriptor_name)
        digest = hashlib.sha256()
        byte_length = 0

        try:
            with (
                source_path.open("rb") as source_handle,
                os.fdopen(
                    descriptor_fd,
                    "wb",
                ) as destination_handle,
            ):
                while chunk := source_handle.read(_COPY_CHUNK_SIZE):
                    destination_handle.write(chunk)
                    digest.update(chunk)
                    byte_length += len(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())

            descriptor = self._descriptor(
                dataset_id=dataset_id,
                source_evidence_id=source_evidence_id,
                content_hash=digest.hexdigest(),
                byte_length=byte_length,
                media_type=media_type,
                provenance=provenance,
                preprocessing_steps=tuple(preprocessing_steps),
            )
            object_path = self._commit_object(temporary_path, descriptor)
            manifest_path = self._commit_manifest(descriptor)
        except OSError as exc:
            raise V2AnalysisDatasetRepositoryError(
                f"dataset source file could not be imported: {source_path}"
            ) from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        return V2StoredAnalysisDataset(
            descriptor=descriptor,
            object_path=object_path,
            manifest_path=manifest_path,
        )

    def get(self, dataset_id: str) -> V2StoredAnalysisDataset:
        manifest_path = self._manifest_path(dataset_id)
        descriptor = self._read_manifest_path(manifest_path)
        if descriptor.dataset_id != dataset_id.strip():
            raise V2AnalysisDatasetIntegrityError(
                "retained analysis dataset ID does not match the requested ID"
            )
        object_path = self._verify_object(descriptor)
        return V2StoredAnalysisDataset(
            descriptor=descriptor,
            object_path=object_path,
            manifest_path=manifest_path,
        )

    def list_datasets(self) -> tuple[V2StoredAnalysisDataset, ...]:
        datasets = []
        for manifest_path in sorted(self._manifests.glob("*.json")):
            descriptor = self._read_manifest_path(manifest_path)
            datasets.append(
                V2StoredAnalysisDataset(
                    descriptor=descriptor,
                    object_path=self._verify_object(descriptor),
                    manifest_path=manifest_path,
                )
            )
        return tuple(sorted(datasets, key=lambda item: item.dataset_id))

    def resolve(self, analysis_input: V2AnalysisInput) -> bytes:
        try:
            stored = self.get(analysis_input.dataset_id)
        except V2AnalysisDatasetNotFoundError as exc:
            raise V2AnalysisDatasetResolutionError(
                str(exc),
                retryable=True,
            ) from exc
        except (
            V2AnalysisDatasetConflictError,
            V2AnalysisDatasetIntegrityError,
        ) as exc:
            raise V2AnalysisInputIntegrityError(str(exc)) from exc
        except V2AnalysisDatasetRepositoryError as exc:
            raise V2AnalysisDatasetResolutionError(
                str(exc),
                retryable=True,
            ) from exc

        if stored.descriptor != analysis_input:
            raise V2AnalysisInputIntegrityError(
                f"retained descriptor for dataset {analysis_input.dataset_id!r} "
                "does not exactly match the analysis job input"
            )

        try:
            payload = stored.object_path.read_bytes()
        except OSError as exc:
            raise V2AnalysisDatasetResolutionError(
                f"retained bytes could not be read for dataset {analysis_input.dataset_id!r}",
                retryable=True,
            ) from exc

        if calculate_dataset_hash(payload) != analysis_input.content_hash:
            raise V2AnalysisInputIntegrityError(
                f"retained byte hash changed for dataset {analysis_input.dataset_id!r}"
            )
        if len(payload) != analysis_input.byte_length:
            raise V2AnalysisInputIntegrityError(
                f"retained byte length changed for dataset {analysis_input.dataset_id!r}"
            )
        return payload
