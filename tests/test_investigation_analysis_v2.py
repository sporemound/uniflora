from __future__ import annotations

from dataclasses import replace

import pytest

from uniflora.engine.v2 import (
    V2AnalysisDerivedValue,
    V2AnalysisError,
    V2AnalysisInput,
    V2AnalysisIntegrityError,
    V2AnalysisJob,
    V2AnalysisMethod,
    V2AnalysisParameter,
    V2AnalysisUncertainty,
    V2AnalysisValue,
    V2SoftwareVersion,
    calculate_analysis_artifact_hash,
    calculate_analysis_job_hash,
    calculate_dataset_hash,
    calculate_input_manifest_hash,
    create_analysis_artifact_envelope,
    create_analysis_job_envelope,
    deserialize_analysis_artifact_envelope,
    deserialize_analysis_job_envelope,
    serialize_analysis_artifact_envelope,
    serialize_analysis_job_envelope,
    verify_analysis_artifact_envelope,
    verify_analysis_job_envelope,
)


def _input(
    dataset_id: str,
    payload: bytes,
    *,
    evidence_id: str,
) -> V2AnalysisInput:
    return V2AnalysisInput(
        dataset_id=dataset_id,
        source_evidence_id=evidence_id,
        content_hash=calculate_dataset_hash(payload),
        byte_length=len(payload),
        media_type="application/octet-stream",
        provenance=f"Retained bytes for {evidence_id}.",
        preprocessing_steps=("byte-order-normalized",),
    )


def _job(
    *,
    job_id: str = "job_phase_alignment",
    method_version: str = "1.0.0",
    reverse: bool = False,
) -> V2AnalysisJob:
    inputs = (
        _input(
            "optical_frames",
            b"optical-frame-bytes",
            evidence_id="optical_record",
        ),
        _input(
            "radio_samples",
            b"radio-sample-bytes",
            evidence_id="radio_return",
        ),
    )
    parameters = (
        V2AnalysisParameter.from_value("window_size", 256, unit="samples"),
        V2AnalysisParameter.from_value(
            "normalization",
            {"center": True, "scale": "robust"},
        ),
    )

    if reverse:
        inputs = tuple(reversed(inputs))
        parameters = tuple(reversed(parameters))

    return V2AnalysisJob(
        job_id=job_id,
        stream_id="investigation_alpha",
        position_id="boundary_event",
        requested_by_player_id="player_a",
        method=V2AnalysisMethod(
            method_id="cross_source_phase_alignment",
            version=method_version,
            implementation="uniflora.science.phase_alignment",
            description=(
                "Estimate relative timing alignment without inferring a physical trajectory."
            ),
        ),
        inputs=inputs,
        parameters=parameters,
        output_kind="phase_alignment_report",
    )


def _artifact_envelope():
    job_envelope = create_analysis_job_envelope(_job())
    artifact_envelope = create_analysis_artifact_envelope(
        job_envelope,
        artifact_id="artifact_phase_alignment",
        derived_values=(
            V2AnalysisDerivedValue.from_value(
                "relative_offset",
                0.018,
                unit="seconds",
            ),
            V2AnalysisDerivedValue.from_value(
                "candidate_offsets",
                [0.017, 0.018, 0.020],
                unit="seconds",
            ),
        ),
        uncertainties=(
            V2AnalysisUncertainty.quantified(
                "clock_alignment",
                "Absolute clock alignment remains bounded by station logs.",
                0.006,
                unit="seconds",
            ),
            V2AnalysisUncertainty(
                source="sampling_coverage",
                statement="The records do not span the complete event.",
            ),
        ),
        limitations=(
            "The result does not establish source distance.",
            "The result does not establish one common emitter.",
        ),
        software_versions=(
            V2SoftwareVersion(name="numpy", version="2.4.0"),
            V2SoftwareVersion(name="uniflora-analysis", version="0.1.0"),
        ),
        provenance=(
            "Job executed by the local scientific worker.",
            "Input bytes were addressed by their SHA-256 digests.",
        ),
    )
    return job_envelope, artifact_envelope


def test_dataset_hash_is_sha256_of_exact_bytes() -> None:
    assert calculate_dataset_hash(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_analysis_values_preserve_nested_canonical_json() -> None:
    value = V2AnalysisValue.from_python(
        {"basis": ["x", "z"], "regularized": True, "threshold": 0.05}
    )

    assert value.canonical_json == ('{"basis":["x","z"],"regularized":true,"threshold":0.05}')
    assert value.to_python() == {
        "basis": ["x", "z"],
        "regularized": True,
        "threshold": 0.05,
    }


def test_noncanonical_analysis_value_is_rejected() -> None:
    with pytest.raises(V2AnalysisError, match="already be canonical"):
        V2AnalysisValue('{"z": 1, "a": 2}')


def test_job_hash_is_independent_of_input_and_parameter_order() -> None:
    first = _job()
    second = _job(reverse=True)

    assert first == second
    assert calculate_input_manifest_hash(first.inputs) == (
        calculate_input_manifest_hash(second.inputs)
    )
    assert calculate_analysis_job_hash(first) == calculate_analysis_job_hash(second)


def test_duplicate_dataset_ids_are_rejected() -> None:
    duplicate = _input(
        "optical_frames",
        b"different-bytes",
        evidence_id="radio_return",
    )
    original = _job()

    with pytest.raises(V2AnalysisError, match="duplicate names"):
        replace(original, inputs=(original.inputs[0], duplicate))


def test_job_envelope_round_trips_canonical_bytes() -> None:
    envelope = create_analysis_job_envelope(_job())
    encoded = serialize_analysis_job_envelope(envelope)

    assert deserialize_analysis_job_envelope(encoded) == envelope
    assert serialize_analysis_job_envelope(deserialize_analysis_job_envelope(encoded)) == encoded
    assert verify_analysis_job_envelope(envelope) == envelope.job


def test_job_tampering_is_detected() -> None:
    envelope = create_analysis_job_envelope(_job())
    changed_job = replace(envelope.job, output_kind="trajectory_solution")

    with pytest.raises(V2AnalysisIntegrityError, match="job hash"):
        verify_analysis_job_envelope(replace(envelope, job=changed_job))


def test_input_manifest_hash_changes_when_input_bytes_change() -> None:
    job = _job()
    changed_input = replace(
        job.inputs[0],
        content_hash=calculate_dataset_hash(b"changed-optical-bytes"),
    )

    assert calculate_input_manifest_hash(job.inputs) != calculate_input_manifest_hash(
        (changed_input, job.inputs[1])
    )


def test_artifact_carries_method_parameters_uncertainty_and_provenance() -> None:
    job_envelope, artifact_envelope = _artifact_envelope()
    artifact = verify_analysis_artifact_envelope(
        artifact_envelope,
        job_envelope=job_envelope,
    )

    assert artifact.job_hash == job_envelope.job_hash
    assert artifact.input_manifest_hash == calculate_input_manifest_hash(job_envelope.job.inputs)
    assert artifact.method_id == job_envelope.job.method.method_id
    assert artifact.method_version == job_envelope.job.method.version
    assert artifact.parameters == job_envelope.job.parameters
    assert {value.name for value in artifact.derived_values} == {
        "candidate_offsets",
        "relative_offset",
    }
    assert len(artifact.uncertainties) == 2
    assert len(artifact.limitations) == 2
    assert len(artifact.software_versions) == 2
    assert len(artifact.provenance) == 2


def test_artifact_envelope_round_trips_canonical_bytes() -> None:
    _, envelope = _artifact_envelope()
    encoded = serialize_analysis_artifact_envelope(envelope)

    assert deserialize_analysis_artifact_envelope(encoded) == envelope
    assert (
        serialize_analysis_artifact_envelope(deserialize_analysis_artifact_envelope(encoded))
        == encoded
    )


def test_artifact_payload_tampering_is_detected() -> None:
    _, envelope = _artifact_envelope()
    changed_artifact = replace(
        envelope.artifact,
        limitations=("The result proves a physical object.",),
    )

    assert calculate_analysis_artifact_hash(changed_artifact) != (envelope.artifact_hash)

    with pytest.raises(V2AnalysisIntegrityError, match="artifact hash"):
        verify_analysis_artifact_envelope(replace(envelope, artifact=changed_artifact))


def test_artifact_cannot_be_verified_against_another_job() -> None:
    _, artifact_envelope = _artifact_envelope()
    other_job = create_analysis_job_envelope(
        _job(job_id="job_phase_alignment_revised", method_version="1.1.0")
    )

    with pytest.raises(V2AnalysisIntegrityError, match="different job"):
        verify_analysis_artifact_envelope(
            artifact_envelope,
            job_envelope=other_job,
        )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"limitations": ()}, "limitation must contain"),
        ({"uncertainties": ()}, "require uncertainty"),
        ({"software_versions": ()}, "require software"),
        ({"provenance": ()}, "provenance must contain"),
    ],
)
def test_successful_artifacts_require_complete_reporting(
    replacement: dict[str, object],
    message: str,
) -> None:
    _, envelope = _artifact_envelope()

    with pytest.raises(V2AnalysisError, match=message):
        replace(envelope.artifact, **replacement)


def test_nonfinite_numeric_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="canonical-JSON"):
        V2AnalysisParameter.from_value("invalid", float("nan"))
